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

        self.alb_sg = ec2.SecurityGroup(
            self,
            "AlbSg",
            vpc=self.vpc,
            description="ALB - allow inbound HTTPS only",
            allow_all_outbound=False,
        )
        self.alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS")
        self.alb_sg.add_egress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(8000), "To ECS tasks")

        self.ecs_sg = ec2.SecurityGroup(
            self,
            "EcsSg",
            vpc=self.vpc,
            description="ECS tasks - allow inbound from ALB only",
            allow_all_outbound=True,
        )
        self.ecs_sg.add_ingress_rule(self.alb_sg, ec2.Port.tcp(8000), "From ALB")

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

        NagSuppressions.add_resource_suppressions(
            self.alb_sg,
            [
                {
                    "id": "AwsSolutions-EC23",
                    "reason": (
                        "Intentional: this is the security group for the internet-facing "
                        "ALB, which must accept HTTPS from any client. Ingress is limited "
                        "to TCP 443; the ECS tasks behind it accept traffic only from this "
                        "security group on port 8000."
                    ),
                }
            ],
        )
