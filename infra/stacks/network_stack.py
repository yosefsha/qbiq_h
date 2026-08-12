from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from cdk_nag import NagSuppressions
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, env_config: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # No NAT Gateway, and therefore no `PRIVATE_WITH_EGRESS` subnets.
        #
        # A NAT Gateway is ~$32/month before a byte of data passes through it, and
        # it was by a wide margin the largest line item in this environment. This
        # is a demo storefront; the cost is not justified by what it buys.
        #
        # **What it bought, and how that is replaced.** The only thing in this VPC
        # that ever needed outbound internet is the ECS task: it pulls its image
        # from ECR and reaches Secrets Manager and CloudWatch Logs at task start.
        # With no NAT, a task in a private subnet cannot do any of that and fails
        # to start with an image-pull timeout — which surfaces as a task that
        # never becomes healthy, i.e. it looks exactly like a health-check bug.
        # So the tasks run in these **public** subnets with a public IP instead
        # (see `task_subnets` / `assign_public_ip` in `backend_stack.py`), which
        # gives them egress through the internet gateway at no hourly cost.
        #
        # **A public IP is not public access.** The task security group admits
        # inbound traffic from the ALB security group alone, on port 8000 and
        # nothing else. Nothing else can open a connection to a task, from the
        # internet or from anywhere.
        #
        # **The data tier does not move.** RDS and ElastiCache stay in the
        # `PRIVATE_ISOLATED` subnets below — no route to an internet gateway at
        # all — reachable only from the ECS task security group. Isolated rather
        # than "with egress" is strictly stronger for them: neither ever needed
        # outbound internet, and now neither has a path to it.
        #
        # **The alternative that was rejected**, so nobody "fixes" this later:
        # interface VPC endpoints for ECR (api and dkr), Secrets Manager and
        # CloudWatch Logs would keep the tasks private, but they cost ~$7.20/month
        # each — four of them is ~$29/month against the NAT's ~$32. That is not a
        # saving, it is the same bill with more moving parts.
        #
        # **The one thing genuinely lost** is the RDS secret's managed rotation
        # Lambda, which needs egress to the Secrets Manager API and no longer has
        # any. See the comment where it used to be, in `data_stack.py`.
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
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
