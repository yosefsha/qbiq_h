from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_logs as logs
from cdk_nag import NagSuppressions
from constructs import Construct


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
