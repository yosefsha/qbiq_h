from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from cdk_nag import NagSuppressions
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, env_config: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # This stack deliberately exports only the VPC.
        #
        # It previously declared an ALB security group and an ECS task security
        # group here. Neither was ever attached to anything — backend_stack's
        # ApplicationLoadBalancedFargateService creates its own — so they read as
        # enforcement while enforcing nothing, which is worse than their absence.
        # Security groups now live in the stack that owns the resource they
        # protect: the task security group is in backend_stack, and the ALB's
        # (with its HTTPS-only listener) arrives with the ACM certificate in
        # INF-06, since an HTTPS listener cannot exist without one.
        #
        # Declaring them here would also be a dependency cycle: the load
        # balancer construct adds an ingress rule to the task security group, so
        # a group owned by this stack would make the network stack depend on the
        # backend stack that already depends on it.

        # Environment/Service/Owner tags are applied once at the App in app.py and
        # propagate into this stack, so they are deliberately not repeated here.

        NagSuppressions.add_resource_suppressions(
            self.vpc,
            [
                {
                    "id": "AwsSolutions-VPC7",
                    "reason": (
                        "VPC flow logs are not enabled yet. They bill per GB ingested "
                        "and need a log destination and retention decision that belongs "
                        "with the observability work, not with the CDK bootstrap. This "
                        "suppression is a placeholder to be removed when flow logs land."
                    ),
                }
            ],
            apply_to_children=True,
        )
