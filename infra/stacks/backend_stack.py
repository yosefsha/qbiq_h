from collections.abc import Mapping, Sequence

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_logs as logs
from cdk_nag import NagSuppressions
from constructs import Construct

from stacks.data_stack import DataClientTarget


#: Name of the application container. The pipeline writes this into
#: imagedefinitions.json, so the two must agree or EcsDeployAction silently
#: matches nothing and the deploy succeeds while changing no image.
CONTAINER_NAME = "backend"


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

        cluster = ecs.Cluster(self, "Cluster", vpc=vpc, container_insights_v2=ecs.ContainerInsights.ENABLED)

        log_group = logs.LogGroup(
            self,
            "BackendLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

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
                container_port=8000,
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="backend",
                    log_group=log_group,
                ),
                # Host, port and database name are not secret and are plain
                # environment variables; the username, password and Redis AUTH
                # token are `valueFrom` references that ECS resolves from
                # Secrets Manager as the task starts, so they never appear in
                # the task definition or in any image layer.
                #
                # These are the parts, not the URLs. `backend/app/settings.py`
                # reads a single `DATABASE_URL` and a single `REDIS_URL`, and
                # assembling those cannot happen at synth time — the password is
                # generated by CloudFormation during the deploy. Composing them
                # at container start belongs with the rest of the runtime
                # configuration (ALLOWED_ORIGINS, COOKIE_SECURE, the TTLs) in
                # INF-05; INF-04 provisions the data tier and must not change
                # application code to get there.
                environment=dict(data_environment),
                secrets=dict(data_secrets),
            ),
            security_groups=[self.task_security_group],
            public_load_balancer=True,
        )

        self.service.target_group.configure_health_check(
            path="/health",
            healthy_http_codes="200",
            interval=Duration.seconds(30),
        )

        scaling = self.service.service.auto_scale_task_count(
            min_capacity=env_config["backend_min_tasks"],
            max_capacity=env_config["backend_max_tasks"],
        )
        scaling.scale_on_cpu_utilization("CpuScaling", target_utilization_percent=70)

        # Environment/Service/Owner tags are applied once at the App in app.py and
        # propagate into this stack, so they are deliberately not repeated here.

        NagSuppressions.add_resource_suppressions(
            self.service.load_balancer,
            [
                {
                    "id": "AwsSolutions-EC23",
                    "reason": (
                        "The ALB is internet-facing and must accept client traffic from "
                        "any address; the tasks behind it are in private subnets and "
                        "reachable only through it. Stated plainly so this is not "
                        "mistaken for compliance: the listener is currently HTTP on "
                        "port 80, NOT HTTPS on 443. An HTTPS listener needs an ACM "
                        "certificate, which needs a real domain — still a placeholder in "
                        "infra/config. When INF-06 sets one, pass `certificate` and "
                        "`redirect_http_to_https=True` here and narrow this suppression."
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
                        "environment variables are the database host, port and name and "
                        "the cache host and port — all of them private DNS names inside "
                        "the VPC, all already visible to anyone who can describe the RDS "
                        "instance. The username, password and Redis AUTH token are "
                        "`secrets` entries, resolved from Secrets Manager at task start. "
                        "Moving non-secret connection details into Secrets Manager would "
                        "add cost and a rotation question for values that are not secret."
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
