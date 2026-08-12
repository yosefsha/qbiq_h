"""API tier: ECR, an ECS Fargate service in private subnets, and an ALB.

References run **backend -> data** and never the other way. Everything this
stack needs from the data tier arrives as constructor arguments, and the
security group rules that let these tasks into Postgres and Redis are
declared here rather than there — see the comment on `data_client_targets`
below, and the matching one in `network_stack.py`.
"""

from collections.abc import Mapping, Sequence

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cloudwatch_actions
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from cdk_nag import NagSuppressions
from constructs import Construct

from stacks.data_stack import DataClientTarget


#: Name of the application container. The pipeline writes this into
#: imagedefinitions.json, so the two must agree or EcsDeployAction silently
#: matches nothing and the deploy succeeds while changing no image.
CONTAINER_NAME = "backend"

#: Port uvicorn listens on inside the container.
CONTAINER_PORT = 8000

#: The X-Ray daemon's UDP receive port, fixed by the daemon itself.
XRAY_DAEMON_PORT = 2000


class BackendStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_config: dict,
        vpc: ec2.IVpc,
        data_environment: Mapping[str, str],
        data_secrets: Mapping[str, ecs.Secret],
        data_client_targets: Sequence[DataClientTarget],
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Owned here rather than in the network stack: the load balancer construct
        # below adds its own ingress rule to this group, so a group belonging to
        # the network stack would create a cycle between the two stacks.
        self.task_security_group = ec2.SecurityGroup(
            self,
            "TaskSg",
            vpc=vpc,
            description="ECS tasks - inbound only from the load balancer on 8000",
            allow_all_outbound=True,
        )

        # The database and cache security groups belong to the data stack, but
        # the rules admitting these tasks are declared here, as raw
        # CfnSecurityGroupIngress resources in *this* stack.
        #
        # Calling `data_sg.add_ingress_rule(self.task_security_group, ...)` would
        # look tidier and be wrong: CDK scopes that rule to the security group's
        # own construct, so it would land in the data stack and make the data
        # stack depend on this one — while this stack already depends on the data
        # stack for the endpoints and secrets below. That pair is a
        # `DependencyCycle` at synth time, the same failure the network stack's
        # comment records. Declaring the rule on this side keeps every reference
        # pointing backend -> data.
        for target in data_client_targets:
            ec2.CfnSecurityGroupIngress(
                self,
                f"{target.id}IngressFromTasks",
                group_id=target.security_group.security_group_id,
                source_security_group_id=self.task_security_group.security_group_id,
                ip_protocol="tcp",
                from_port=target.port,
                to_port=target.port,
                description=target.description,
            )

        self.ecr_repo = ecr.Repository(
            self,
            "BackendRepo",
            repository_name=f"{env_config['service_name']}-backend",
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=20)],
        )

        cluster = ecs.Cluster(
            self, "Cluster", vpc=vpc, container_insights_v2=ecs.ContainerInsights.ENABLED
        )

        log_group = logs.LogGroup(
            self,
            "BackendLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        listener = self._listener_configuration(env_config)

        self.service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "BackendService",
            cluster=cluster,
            cpu=256,
            memory_limit_mib=512,
            desired_count=env_config["backend_desired_count"],
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                # `latest` is a bootstrap tag only. Steady-state image selection
                # is owned by the pipeline's EcsDeployAction, which overrides
                # this with the commit-SHA tag from imagedefinitions.json. The
                # pipeline pushes both tags so this reference is resolvable.
                #
                # Chicken-and-egg on a brand new environment: ECR is empty at
                # first `cdk deploy`, so tasks cannot pull and the service never
                # stabilises. Run the pipeline's build once (or push any image
                # to the repo by hand) before the first deploy of this stack.
                image=ecs.ContainerImage.from_ecr_repository(self.ecr_repo, "latest"),
                container_name=CONTAINER_NAME,
                container_port=CONTAINER_PORT,
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="backend",
                    log_group=log_group,
                ),
                environment=self._task_environment(env_config, data_environment),
                secrets=dict(data_secrets),
            ),
            security_groups=[self.task_security_group],
            public_load_balancer=True,
            # CLAUDE.md's rolling deployment, stated explicitly rather than
            # inherited: without these, CDK warns at synth that the 50% default
            # applies and half the tasks are drained before a replacement is
            # healthy. 100/200 replaces the old set only once the new set is in
            # the target group.
            min_healthy_percent=100,
            max_healthy_percent=200,
            # A task that cannot reach Postgres or Redis never passes its health
            # check (see backend/app/health.py), so without a circuit breaker a
            # misconfigured release sits in a replacement loop for up to three
            # hours before CloudFormation gives up. With it, the deployment
            # fails fast and rolls back to the last task set that was healthy.
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True),
            # The container has to import the app, build the SQLAlchemy engine
            # and open its first connections before `/health` can answer. Longer
            # than the grace period and the very first check would kill the task
            # that was about to become healthy.
            health_check_grace_period=Duration.seconds(60),
            **listener,
        )

        # `/health` is a real dependency check on first pass and a boolean read
        # afterwards (backend/app/health.py), so it is cheap enough to run every
        # 30s per task and still means something: a task that was handed the
        # wrong connection details never reports 200 and never joins the target
        # group.
        self.service.target_group.configure_health_check(
            path="/health",
            healthy_http_codes="200",
            interval=Duration.seconds(30),
            timeout=Duration.seconds(5),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3,
        )
        # The default is 300s, during which a rolling deployment holds the old
        # tasks open. Nothing here streams or holds a long request, so 30s is
        # ample for in-flight work to finish and takes ~4 minutes off a deploy.
        self.service.target_group.set_attribute(
            "deregistration_delay.timeout_seconds", "30"
        )

        scaling = self.service.service.auto_scale_task_count(
            min_capacity=env_config["backend_min_tasks"],
            max_capacity=env_config["backend_max_tasks"],
        )
        scaling.scale_on_cpu_utilization("CpuScaling", target_utilization_percent=70)

        self._add_xray_daemon(log_group)
        self.alarm_topic = self._add_alarms(env_config)

        CfnOutput(
            self,
            "LoadBalancerDnsName",
            value=self.service.load_balancer.load_balancer_dns_name,
        )
        CfnOutput(self, "EcrRepositoryUri", value=self.ecr_repo.repository_uri)

        # Environment/Service/Owner tags are applied once at the App in app.py and
        # propagate into this stack, so they are deliberately not repeated here.

        self._suppress_nag_findings(https_enabled="certificate" in listener)

    # ------------------------------------------------------------------
    # Task configuration
    # ------------------------------------------------------------------
    def _task_environment(
        self, env_config: dict, data_environment: Mapping[str, str]
    ) -> dict[str, str]:
        """Plain, non-secret environment variables for the application container.

        `data_environment` carries the data tier's host/port/name parts. Host,
        port and database name are not secret; the username, password and Redis
        AUTH token are `secrets` entries that ECS resolves from Secrets Manager
        as the task starts, so they never appear in the task definition or in
        any image layer.

        Those are the *parts*, not the URLs, because the password is generated
        by CloudFormation during the deploy and nothing at synth time can see
        it. `backend/app/settings.py` composes `DATABASE_URL` and `REDIS_URL`
        from them at import time, percent-encoding the credentials — see the
        module docstring there. Before that change these variables were injected
        and read by nothing at all: the container fell back to its localhost
        defaults, failed every query, and still answered `/health` with a 200.
        """
        return {
            **data_environment,
            # ADR-001: the SPA and the API share one origin through the
            # CloudFront `/api/*` behaviour, so this list exists for the
            # non-proxied case and must never be a wildcard next to
            # allow_credentials=True.
            "ALLOWED_ORIGINS": f"https://{env_config['frontend_domain']}",
            # Everything the browser sees is HTTPS at CloudFront, so the session
            # cookie is Secure. Locally it is not — see docker-compose.yml.
            "COOKIE_SECURE": "true",
            "CACHE_TTL_SECONDS": str(env_config["cache_ttl_seconds"]),
            "SESSION_TTL_SECONDS": str(env_config["session_ttl_seconds"]),
            "LOG_LEVEL": env_config["log_level"],
        }

    def _listener_configuration(self, env_config: dict) -> dict:
        """Returns the listener props for `ApplicationLoadBalancedFargateService`.

        CLAUDE.md requires the ALB to admit 443 only, and that needs an ACM
        certificate, which needs a real domain. `domain_name` in
        `infra/config/` is still `example.com`, answered by a fake hosted-zone
        id seeded into `cdk.json`, so there is no certificate to attach and
        inventing one would produce a template that cannot deploy.

        So the listener is configuration, not a promise. `alb_listener_protocol`
        is the single switch, and it is deliberately the same key
        `frontend_stack.py` reads for CloudFront's `OriginProtocolPolicy` on the
        `/api/*` behaviour (INF-06): two settings for one fact would let the
        edge be told to speak HTTPS to an origin listening on HTTP, which is a
        502 at CloudFront that nothing in the application log explains.

        `HTTPS` additionally needs `alb_certificate_arn`, which is a different
        fact — *which* certificate, not *whether* TLS — and is required rather
        than inferred, so a half-configured environment fails at synth instead
        of quietly deploying plaintext.

        **The certificate has to cover `frontend_domain`.** CloudFront's
        `/api/*` behaviour forwards the viewer's `Host` header (the AllViewer
        origin request policy) and uses that value for SNI to this ALB, so a
        certificate issued for `*.elb.amazonaws.com` fails the handshake. Issue
        it for the same name the SPA is served on.

        `docs/runbook.md` records exactly what remains manual.
        """
        protocol = str(env_config.get("alb_listener_protocol", "HTTP")).upper()
        if protocol == "HTTP":
            return {}
        if protocol != "HTTPS":
            raise ValueError(
                f"alb_listener_protocol must be 'HTTP' or 'HTTPS', not {protocol!r}."
            )

        certificate_arn = env_config.get("alb_certificate_arn") or ""
        if not certificate_arn:
            raise ValueError(
                "alb_listener_protocol is 'HTTPS' but alb_certificate_arn is empty. "
                "An HTTPS listener needs an ACM certificate in this region covering "
                f"{env_config['frontend_domain']} — see docs/runbook.md."
            )

        return {
            "certificate": acm.Certificate.from_certificate_arn(
                self, "AlbCertificate", certificate_arn
            ),
            "protocol": elbv2.ApplicationProtocol.HTTPS,
            "listener_port": 443,
            # The redirect listener is the only thing left on 80. A client that
            # arrives there is sent to 443 before it can send a cookie in clear.
            # Note this means the ALB is not literally "443 only" even in this
            # mode: 80 stays open, answering nothing but a 301.
            "redirect_http": True,
            "ssl_policy": elbv2.SslPolicy.RECOMMENDED_TLS,
        }

    def _add_xray_daemon(self, log_group: logs.LogGroup) -> None:
        """Adds the X-Ray daemon sidecar and the task role permissions it needs.

        This is the receiving half of tracing: the daemon buffers segments on
        UDP 2000 inside the task and ships them to X-Ray. **Read this before
        expecting traces** — the application does not emit segments yet, so
        today the daemon runs and forwards nothing. An ALB cannot be "traced"
        on its own either; it only stamps `X-Amzn-Trace-Id` on the request, and
        something in the task has to pick that header up and open a segment
        under it. Instrumenting FastAPI is application work and is deliberately
        not smuggled into this stack; the transport and the IAM grant are here
        so that change is a one-line dependency away from working.

        `essential=False`: if the daemon dies, the task keeps serving. Losing
        traces is not a reason to take a healthy API task out of the target
        group.
        """
        self.service.task_definition.add_container(
            "XRayDaemon",
            image=ecs.ContainerImage.from_registry(
                "public.ecr.aws/xray/aws-xray-daemon:3.x"
            ),
            essential=False,
            cpu=32,
            memory_reservation_mib=64,
            port_mappings=[
                ecs.PortMapping(
                    container_port=XRAY_DAEMON_PORT, protocol=ecs.Protocol.UDP
                )
            ],
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="xray", log_group=log_group
            ),
        )

        self.service.task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=[
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                    "xray:GetSamplingStatisticSummaries",
                ],
                resources=["*"],
            )
        )

    # ------------------------------------------------------------------
    # Alarms
    # ------------------------------------------------------------------
    def _add_alarms(self, env_config: dict) -> sns.Topic:
        """The three alarms CLAUDE.md names, and the topic they notify.

        The topic is created with no subscription unless `alarm_email` is set
        in `infra/config/<env>.py`: an endpoint is a real address or a real
        PagerDuty integration key, and neither belongs in this repository.
        An alarm with a topic nobody is subscribed to still changes state and
        is still visible in the console — it just does not wake anyone, which
        is recorded in `docs/runbook.md` rather than left to be discovered.
        """
        # enforce_ssl adds a topic policy denying Publish over plain HTTP,
        # which resolves AwsSolutions-SNS3 outright rather than suppressing it.
        topic = sns.Topic(
            self,
            "AlarmTopic",
            display_name=f"{env_config['service_name']} {env_config['environment']} alarms",
            enforce_ssl=True,
        )

        alarm_email = env_config.get("alarm_email")
        if alarm_email:
            topic.add_subscription(subscriptions.EmailSubscription(alarm_email))

        action = cloudwatch_actions.SnsAction(topic)

        load_balancer = self.service.load_balancer
        target_group = self.service.target_group

        # 5xx as a *proportion* of requests, not a count: a fixed count fires on
        # a quiet night at a rate nobody would notice at midday, and stays
        # silent during a partial outage at peak. Both ELB-generated 5xx (no
        # healthy target, or a target that timed out) and target-generated 5xx
        # (the application's own errors) count, because to a Shopper they are
        # the same failure.
        error_rate = cloudwatch.MathExpression(
            expression="100 * (elb5xx + target5xx) / requests",
            using_metrics={
                "elb5xx": load_balancer.metrics.http_code_elb(
                    elbv2.HttpCodeElb.ELB_5XX_COUNT, statistic="Sum"
                ),
                "target5xx": target_group.metrics.http_code_target(
                    elbv2.HttpCodeTarget.TARGET_5XX_COUNT, statistic="Sum"
                ),
                "requests": load_balancer.metrics.request_count(statistic="Sum"),
            },
            period=Duration.minutes(5),
            label="5xx rate (%)",
        )

        cloudwatch.Alarm(
            self,
            "Alb5xxRate",
            metric=error_rate,
            threshold=1,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            # No requests means no ratio, and no ratio is not a problem. An ALB
            # that is genuinely down is caught by the unhealthy-host alarm.
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description=(
                "More than 1% of requests through the ALB are failing with a 5xx. "
                "Check the backend log group for `request failed` lines, filtered by "
                "the request id from the client's X-Request-Id header."
            ),
        ).add_alarm_action(action)

        cloudwatch.Alarm(
            self,
            "ServiceCpuHigh",
            metric=self.service.service.metric_cpu_utilization(
                statistic="Average", period=Duration.minutes(5)
            ),
            threshold=80,
            evaluation_periods=3,
            comparison_operator=(
                cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD
            ),
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description=(
                "ECS service CPU is above 80%. Autoscaling targets 70%, so this "
                "firing for 15 minutes means scaling is not keeping up — check "
                "whether max capacity has been reached."
            ),
        ).add_alarm_action(action)

        cloudwatch.Alarm(
            self,
            "UnhealthyTargets",
            metric=target_group.metrics.unhealthy_host_count(
                statistic="Maximum", period=Duration.minutes(1)
            ),
            threshold=0,
            evaluation_periods=3,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            # Deliberately not NOT_BREACHING: the metric is absent when there
            # are no registered targets at all, which is the worst state the
            # service can be in, not a quiet one.
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
            alarm_description=(
                "At least one task is failing the /health check. A task that has "
                "never been healthy is usually misconfigured — look for "
                "`health check dependency unavailable` in the backend log group."
            ),
        ).add_alarm_action(action)

        return topic

    # ------------------------------------------------------------------
    # cdk-nag
    # ------------------------------------------------------------------
    def _suppress_nag_findings(self, https_enabled: bool) -> None:
        listener_state = (
            "The listener is HTTPS on 443 with an HTTP:80 listener that only "
            "redirects to it."
            if https_enabled
            else (
                "Stated plainly so this is not mistaken for compliance: the "
                "listener is currently HTTP on port 80, NOT HTTPS on 443. An "
                "HTTPS listener needs an ACM certificate, which needs a real "
                "domain — still a placeholder in infra/config. Set "
                "`alb_certificate_arn` there and this stack switches to 443 "
                "with a redirect; see docs/runbook.md."
            )
        )

        NagSuppressions.add_resource_suppressions(
            self.service.load_balancer,
            [
                {
                    "id": "AwsSolutions-EC23",
                    "reason": (
                        "The ALB is internet-facing and must accept client traffic from "
                        "any address; the tasks behind it are in private subnets and "
                        f"reachable only through it. {listener_state}"
                    ),
                },
                {
                    "id": "AwsSolutions-ELB2",
                    "reason": (
                        "ALB access logs need a dedicated S3 log bucket with its own "
                        "lifecycle and retention policy, which is not created here. "
                        "Remove this suppression when that bucket exists."
                    ),
                },
            ],
            apply_to_children=True,
        )

        NagSuppressions.add_resource_suppressions(
            self.service.task_definition,
            [
                {
                    "id": "AwsSolutions-ECS2",
                    "reason": (
                        "The rule exists to stop credentials being pasted into a task "
                        "definition, where anyone with ecs:DescribeTaskDefinition can read "
                        "them. Nothing sensitive is passed that way here: the plain "
                        "environment variables are the database host, port and name, the "
                        "cache host and port, the CORS origin list, the cookie flag, two "
                        "TTLs and a log level — all of them either public or private DNS "
                        "names inside the VPC that anyone who can describe the RDS "
                        "instance already sees. The username, password and Redis AUTH "
                        "token are `secrets` entries, resolved from Secrets Manager at "
                        "task start. Moving non-secret connection details into Secrets "
                        "Manager would add cost and a rotation question for values that "
                        "are not secret."
                    ),
                }
            ],
        )

        NagSuppressions.add_resource_suppressions(
            self.service.task_definition.execution_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Wildcards here are in the CDK-generated ECS task execution "
                        "policy: ecr:GetAuthorizationToken is only valid on Resource '*' "
                        "per the ECR API, and the CloudWatch Logs grant is scoped to this "
                        "stack's own log group. Neither is written by us and neither can "
                        "be narrowed further."
                    ),
                }
            ],
            apply_to_children=True,
        )

        NagSuppressions.add_resource_suppressions(
            self.service.task_definition.task_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "The X-Ray write actions (PutTraceSegments, PutTelemetryRecords "
                        "and the three sampling reads) take no resource ARN at all — the "
                        "X-Ray API defines them only against '*', so there is nothing to "
                        "scope them to. They grant no read access to any trace."
                    ),
                }
            ],
            apply_to_children=True,
        )
