"""GitHub Actions' way in: an OIDC trust, one least-privilege role, and outputs.

This stack replaces `pipeline_stack.py` (CodePipeline + CodeBuild). The reasoning
is in [ADR-004](../../docs/adr/ADR-004-github-actions-over-codepipeline.md); the
short version is that CodePipeline re-ran the tests `.github/workflows/ci.yml`
already runs, and its GitHub source needed a CodeStar connection that a human had
to authorise in the console before the pipeline would ever trigger.

Two things this stack is deliberately **not**:

- It is not a deployer of infrastructure. The role below can push an image, run a
  migration task, update one ECS service, write one S3 bucket and invalidate one
  distribution. It cannot run `cdk deploy`, create IAM, or touch RDS. Infrastructure
  changes stay a human running the CDK CLI with their own credentials — a
  deploy-on-merge role that can rewrite its own trust policy is not a deploy role,
  it is an administrator.
- It is not a store of credentials. There is no access key anywhere in this stack
  or in the repository. GitHub presents a short-lived OIDC token, IAM checks the
  claims below, and STS hands back credentials that expire with the job.
"""

from aws_cdk import CfnOutput, Duration, Fn, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from cdk_nag import NagSuppressions
from constructs import Construct

#: The issuer GitHub signs Actions OIDC tokens with. Fixed by GitHub.
GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_HOST = "token.actions.githubusercontent.com"

#: The only audience `aws-actions/configure-aws-credentials` requests. Required in
#: the trust policy: without an `aud` condition the role would accept a token
#: minted for *any* audience, which is the difference between "a token GitHub
#: issued for AWS" and "a token GitHub issued".
GITHUB_OIDC_AUDIENCE = "sts.amazonaws.com"


class DeployStack(Stack):
    """The IAM half of the deploy. The other half is `.github/workflows/deploy.yml`."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_config: dict,
        vpc: ec2.IVpc,
        ecr_repo: ecr.IRepository,
        service: ecs.IBaseService,
        task_definition: ecs.TaskDefinition,
        container_name: str,
        migration_task_definition: ecs.TaskDefinition,
        migration_container_name: str,
        task_security_group: ec2.ISecurityGroup,
        frontend_bucket: s3.IBucket,
        distribution: cloudfront.IDistribution,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        owner = env_config["github_owner"]
        repo = env_config["github_repo"]
        github_environment = env_config["github_environment"]

        provider = self._oidc_provider(env_config)

        # ------------------------------------------------------------------
        # The trust policy. This is the security boundary of the whole change.
        # ------------------------------------------------------------------
        #
        # `sub` is scoped to one repository AND one GitHub environment. The
        # tempting shorter form, `repo:yosefsha/qbiq_h:*`, is what makes OIDC
        # setups dangerous: it matches every branch and every pull request in the
        # repository, so anyone who can open a PR can run a workflow that assumes
        # this role.
        #
        # Environment rather than ref, and only one value, on purpose. Every job in
        # `deploy.yml` that assumes this role declares `environment:` — and when a
        # job declares an environment, GitHub's default subject claim becomes
        # `repo:<owner>/<repo>:environment:<name>` and *stops* carrying the ref. So
        # `repo:...:ref:refs/heads/main` would never be presented by any job here;
        # adding it would widen the trust to jobs that do not exist rather than
        # narrow it to the branch.
        #
        # **What IAM therefore cannot enforce, and who does.** One token carries one
        # `sub`, so the trust policy cannot require branch *and* environment
        # together. The branch restriction lives on the GitHub side, in the
        # environment's deployment-branch policy — see docs/runbook.md, which lists
        # it as a step a human must perform. Until it is set, a `workflow_dispatch`
        # from any branch that names this environment can assume this role. The
        # workflow's `if: github.ref == 'refs/heads/main'` guard closes the same
        # hole from the other side, but it lives in a file that a branch can edit,
        # so it is a convenience, not the control.
        subject = f"repo:{owner}/{repo}:environment:{github_environment}"

        self.role = iam.Role(
            self,
            "GitHubActionsDeployRole",
            # Named, not generated: the workflow builds this ARN from the account
            # id and the environment before it has any credentials to look
            # anything up with, so the name has to be predictable.
            role_name=(
                f"{env_config['service_name']}-{env_config['environment']}"
                "-github-actions-deploy"
            ),
            description=(
                f"Assumed by GitHub Actions from {owner}/{repo}, environment "
                f"{github_environment}. Deploys the application; cannot deploy "
                "infrastructure."
            ),
            assumed_by=iam.OpenIdConnectPrincipal(
                provider,
                conditions={
                    "StringEquals": {
                        f"{GITHUB_OIDC_HOST}:aud": GITHUB_OIDC_AUDIENCE,
                        f"{GITHUB_OIDC_HOST}:sub": subject,
                    }
                },
            ),
            # Stated rather than inherited. A backend deploy waits for the ECS
            # service to stabilise, which the workflow caps at 20 minutes, so one
            # hour is ample — and it is the ceiling on how long a leaked set of
            # credentials from a compromised runner stays usable.
            max_session_duration=Duration.hours(1),
        )

        cluster = service.cluster

        self._grant_ecr(ecr_repo)
        self._grant_ecs(
            service=service,
            cluster=cluster,
            migration_task_definition=migration_task_definition,
        )
        self._grant_pass_role(
            [task_definition, migration_task_definition],
        )
        self._grant_frontend(frontend_bucket, distribution)
        self._grant_read_own_outputs()

        # ------------------------------------------------------------------
        # Everything the workflow needs, resolved at deploy time rather than
        # pasted into YAML. `deploy.yml` reads these with a single
        # `aws cloudformation describe-stacks --stack-name <env>-deploy`, so an
        # ARN never appears in the repository and a re-deploy that changes a
        # generated name does not silently break the workflow.
        #
        # The output *keys* are the contract. Renaming one breaks `deploy.yml`,
        # which greps for it by name.
        # ------------------------------------------------------------------
        private_subnets = vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        )

        outputs = {
            "GitHubActionsRoleArn": self.role.role_arn,
            "AwsRegion": self.region,
            "EcrRepositoryUri": ecr_repo.repository_uri,
            "EcsClusterName": cluster.cluster_name,
            "EcsServiceName": service.service_name,
            "BackendTaskDefinitionFamily": task_definition.family,
            "BackendContainerName": container_name,
            "MigrationTaskDefinitionFamily": migration_task_definition.family,
            "MigrationContainerName": migration_container_name,
            # `aws ecs run-task` needs an explicit awsvpc configuration; a Fargate
            # task launched outside a service inherits nothing from the service.
            # These are the same private subnets and the same security group the
            # service's tasks use, which is what lets the migration reach RDS —
            # the ingress rule in backend_stack.py admits this security group and
            # nothing else.
            "DeploySubnetIds": Fn.join(",", private_subnets.subnet_ids),
            "DeploySecurityGroupId": task_security_group.security_group_id,
            "FrontendBucketName": frontend_bucket.bucket_name,
            "CloudFrontDistributionId": distribution.distribution_id,
        }
        for key, value in outputs.items():
            CfnOutput(self, key, value=value)

        # Environment/Service/Owner tags are applied once at the App in app.py and
        # propagate into this stack, so they are deliberately not repeated here.

        self._suppress_nag_findings(env_config)

    # ------------------------------------------------------------------
    # OIDC provider
    # ------------------------------------------------------------------
    def _oidc_provider(self, env_config: dict) -> iam.IOpenIdConnectProvider:
        """The account-wide trust in GitHub's token issuer.

        An IAM OIDC provider is keyed by its URL and is **account-global**: a second
        `AWS::IAM::OIDCProvider` for `token.actions.githubusercontent.com` in the
        same account fails with `EntityAlreadyExists`. Staging and production share
        an account here (see the note at the top of `infra/config/prod.py`), so
        exactly one environment may own the provider and the other must import it.

        `create_github_oidc_provider` is that switch. It is `True` in staging and
        `False` in production today, which also fixes a deploy order:
        `staging-deploy` must exist before `prod-deploy`. Split the accounts and
        both flip to `True`, and the ordering constraint disappears with them.

        The imported ARN is not guessed — an OIDC provider's ARN is fully
        determined by its account and its URL, so it can be constructed rather
        than configured.
        """
        provider_arn = self.format_arn(
            service="iam",
            region="",
            resource="oidc-provider",
            resource_name=GITHUB_OIDC_HOST,
        )

        if not env_config.get("create_github_oidc_provider"):
            return iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(
                self, "GitHubOidcProvider", provider_arn
            )

        # No `thumbprints`: IAM has verified this issuer against a trusted root CA
        # since 2023 and ignores the thumbprint for it. The CDK construct fetches
        # one anyway via its custom resource; pinning one here would be a value
        # that expires when GitHub rotates its intermediate certificate and breaks
        # every deploy at once.
        return iam.OpenIdConnectProvider(
            self,
            "GitHubOidcProvider",
            url=GITHUB_OIDC_URL,
            client_ids=[GITHUB_OIDC_AUDIENCE],
        )

    # ------------------------------------------------------------------
    # Permissions, one concern per method
    # ------------------------------------------------------------------
    def _grant_ecr(self, ecr_repo: ecr.IRepository) -> None:
        # `docker login`. The ECR API defines GetAuthorizationToken against no
        # resource at all, so '*' is the only value it accepts. It returns a token
        # scoped to the caller's own permissions, so it grants no access on its
        # own — the statement below is what decides which repository can be
        # written.
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="EcrLogin",
                actions=["ecr:GetAuthorizationToken"],
                resources=["*"],
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="EcrPushThisRepositoryOnly",
                actions=[
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:CompleteLayerUpload",
                    "ecr:PutImage",
                    # Reads, so `docker build --cache-from` and a re-run that
                    # re-tags an existing image both work.
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:DescribeImages",
                ],
                resources=[ecr_repo.repository_arn],
            )
        )

    def _grant_ecs(
        self,
        service: ecs.IBaseService,
        cluster: ecs.ICluster,
        migration_task_definition: ecs.TaskDefinition,
    ) -> None:
        # RegisterTaskDefinition and DescribeTaskDefinition support no
        # resource-level permissions at all — the IAM service reference lists no
        # resource type for either, so '*' is the only valid value. The
        # containment is `iam:PassRole` below: a registered task definition is
        # inert unless it can name a task role, and this role can pass exactly two
        # of them.
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="EcsTaskDefinitionRegistration",
                actions=[
                    "ecs:RegisterTaskDefinition",
                    "ecs:DescribeTaskDefinition",
                ],
                resources=["*"],
            )
        )

        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="EcsUpdateThisServiceOnly",
                actions=["ecs:UpdateService", "ecs:DescribeServices"],
                resources=[service.service_arn],
            )
        )

        # The migration. `ecs:RunTask` takes the task *definition* as its resource,
        # and the revision is not known until the workflow registers it, so the
        # ARN is the family with a `:*` revision wildcard — the family name is
        # fixed in backend_stack.py precisely so this can be written down. The
        # `ecs:cluster` condition pins it to this environment's cluster, so the
        # wildcard cannot be used to start the task somewhere else.
        migration_family_arn = self.format_arn(
            service="ecs",
            resource="task-definition",
            resource_name=f"{migration_task_definition.family}:*",
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="EcsRunMigrationTask",
                actions=["ecs:RunTask"],
                resources=[migration_family_arn],
                conditions={"StringEquals": {"ecs:cluster": cluster.cluster_arn}},
            )
        )

        # `aws ecs run-task` returning 200 means the task was *accepted*, not that
        # it succeeded. DescribeTasks is how the exit code is read, and without it
        # a failed migration is indistinguishable from a successful one. Task ids
        # are generated per run, so the resource is a wildcard under this cluster's
        # own path and is fenced by the same `ecs:cluster` condition.
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="EcsReadTaskStateInThisClusterOnly",
                actions=["ecs:DescribeTasks"],
                resources=[
                    self.format_arn(
                        service="ecs",
                        resource="task",
                        resource_name=f"{cluster.cluster_name}/*",
                    )
                ],
                conditions={"StringEquals": {"ecs:cluster": cluster.cluster_arn}},
            )
        )

    def _grant_pass_role(
        self, task_definitions: list[ecs.TaskDefinition]
    ) -> None:
        """`iam:PassRole` for the four ECS roles, and for nothing else.

        This is the statement that decides what a registered task definition may
        become. Without the `iam:PassedToService` condition, a role that can pass
        an execution role can hand it to any service that accepts one; with it,
        the only thing on the other end can be an ECS task.
        """
        role_arns = []
        for task_definition in task_definitions:
            role_arns.append(task_definition.task_role.role_arn)
            if task_definition.execution_role is not None:
                role_arns.append(task_definition.execution_role.role_arn)

        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="PassEcsTaskRolesOnly",
                actions=["iam:PassRole"],
                resources=role_arns,
                conditions={
                    "StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}
                },
            )
        )

    def _grant_frontend(
        self, bucket: s3.IBucket, distribution: cloudfront.IDistribution
    ) -> None:
        # `aws s3 sync --delete` reads the bucket listing to decide what to upload
        # and what to remove, so ListBucket is not optional. GetObject is what
        # makes the sync a sync rather than a full re-upload on every deploy.
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="S3SyncThisBucketOnly",
                actions=["s3:ListBucket", "s3:GetBucketLocation"],
                resources=[bucket.bucket_arn],
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="S3WriteThisBucketOnly",
                actions=["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                resources=[bucket.arn_for_objects("*")],
            )
        )

        # GetInvalidation as well as CreateInvalidation: the workflow waits for the
        # invalidation to complete, so that "deployed" means the edge is serving
        # the new index.html rather than that a request to create an invalidation
        # was accepted.
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudFrontInvalidateThisDistributionOnly",
                actions=["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"],
                resources=[
                    self.format_arn(
                        service="cloudfront",
                        region="",
                        resource="distribution",
                        resource_name=distribution.distribution_id,
                    )
                ],
            )
        )

    def _grant_read_own_outputs(self) -> None:
        # How the workflow learns the cluster name, the bucket, the distribution id
        # and the rest without any of them being hardcoded. Scoped to this stack
        # alone: it grants no visibility into the network, data or backend stacks.
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="ReadThisStackOutputs",
                actions=["cloudformation:DescribeStacks"],
                resources=[self.stack_id],
            )
        )

    # ------------------------------------------------------------------
    # cdk-nag
    # ------------------------------------------------------------------
    def _suppress_nag_findings(self, env_config: dict) -> None:
        NagSuppressions.add_resource_suppressions(
            self.role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Four wildcards, each one forced by an API rather than "
                        "chosen. (1) ecr:GetAuthorizationToken is defined against no "
                        "resource type, so '*' is its only legal value, and the token "
                        "it returns carries the caller's own permissions. "
                        "(2) ecs:RegisterTaskDefinition and ecs:DescribeTaskDefinition "
                        "likewise support no resource-level permissions; the real "
                        "containment is the iam:PassRole statement, which names two "
                        "task roles and two execution roles and requires "
                        "iam:PassedToService=ecs-tasks.amazonaws.com. (3) ecs:RunTask "
                        "is scoped to one task-definition family with a revision "
                        "wildcard, because the revision is created by the deploy that "
                        "uses it, and is additionally conditioned on ecs:cluster. "
                        "(4) ecs:DescribeTasks and the S3 object actions are wildcards "
                        "over task ids and object keys that are generated per run and "
                        "cannot be enumerated in advance; both are confined to this "
                        "environment's own cluster and bucket. No statement in this "
                        "role names Resource '*' for anything that can create, modify "
                        "or read state."
                    ),
                }
            ],
            apply_to_children=True,
        )

        if not env_config.get("create_github_oidc_provider"):
            return

        # `iam.OpenIdConnectProvider` is backed by a CDK-generated custom resource
        # (a small Lambda that calls CreateOpenIDConnectProvider and fetches the
        # issuer thumbprint). Its role and runtime are not ours to configure.
        NagSuppressions.add_resource_suppressions_by_path(
            self,
            f"/{self.stack_name}/Custom::AWSCDKOpenIdConnectProviderCustomResourceProvider",
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AWSLambdaBasicExecutionRole on the CDK-generated custom "
                        "resource that creates the OIDC provider. The construct owns "
                        "this role; it cannot be replaced without vendoring the "
                        "construct, and the managed policy grants only CloudWatch "
                        "Logs writes."
                    ),
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "The same CDK-generated custom resource role. Its wildcard is "
                        "iam:*OpenIDConnectProvider*, which the construct needs "
                        "because the provider does not exist until the resource "
                        "creates it, so there is no ARN to name."
                    ),
                },
                {
                    "id": "AwsSolutions-L1",
                    "reason": (
                        "The runtime of the CDK-generated custom resource Lambda is "
                        "chosen by aws-cdk-lib, not by this stack. It moves when the "
                        "pinned aws-cdk-lib version in infra/requirements.txt moves."
                    ),
                },
            ],
            apply_to_children=True,
        )
