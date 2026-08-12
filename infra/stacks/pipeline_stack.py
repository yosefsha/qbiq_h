from aws_cdk import Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_codepipeline as codepipeline
from aws_cdk import aws_codepipeline_actions as actions
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from cdk_nag import NagSuppressions
from constructs import Construct


class PipelineStack(Stack):
    """Builds and deploys both services for a single environment.

    This pipeline is scoped to one environment, because it holds direct
    references to that environment's ECS service, S3 bucket and CloudFront
    distribution. A single pipeline that promotes staging to production needs
    either cross-account deploy roles or CDK Pipelines' stage construct; it
    cannot be expressed by pointing one stack at two sets of resources. That
    restructuring belongs to INF-07 — see the PR discussion. Until then, the
    production pipeline gates its deploy behind a manual approval.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_config: dict,
        ecr_repo: ecr.IRepository,
        service: ecs.IBaseService,
        container_name: str,
        frontend_bucket: s3.IBucket,
        distribution: cloudfront.IDistribution,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        is_production = env_config["environment"] == "prod"

        source_output = codepipeline.Artifact("SourceOutput")
        backend_build_output = codepipeline.Artifact("BackendBuildOutput")
        frontend_build_output = codepipeline.Artifact("FrontendBuildOutput")

        source_action = actions.CodeStarConnectionsSourceAction(
            action_name="GitHub",
            owner=env_config["github_owner"],
            repo=env_config["github_repo"],
            branch=env_config["github_branch"],
            connection_arn=env_config["codestar_connection_arn"],
            output=source_output,
        )

        # Every command below runs from `backend/`: the services live in
        # backend/ and frontend/, not at the repository root.
        backend_build = codebuild.PipelineProject(
            self,
            "BackendBuild",
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {"python": "3.12"},
                        "commands": [
                            "cd backend",
                            # requirements.txt is runtime-only; pytest and httpx
                            # live in requirements-dev.txt so they stay out of
                            # the runtime image.
                            "pip install -r requirements-dev.txt",
                        ],
                    },
                    "pre_build": {
                        "commands": [
                            "cd backend",
                            "pytest -q",
                        ],
                    },
                    "build": {
                        "commands": [
                            "cd backend",
                            "aws ecr get-login-password --region $AWS_DEFAULT_REGION"
                            " | docker login --username AWS --password-stdin $ECR_REGISTRY",
                            "docker build -t $ECR_REPO_URI:$CODEBUILD_RESOLVED_SOURCE_VERSION"
                            " -t $ECR_REPO_URI:latest .",
                            "docker push $ECR_REPO_URI:$CODEBUILD_RESOLVED_SOURCE_VERSION",
                            # `latest` is pushed as well so that the task
                            # definition rendered by CDK has something to pull
                            # on a first deploy, before any EcsDeployAction has
                            # ever overridden the image.
                            "docker push $ECR_REPO_URI:latest",
                        ],
                    },
                    "post_build": {
                        "commands": [
                            "cd backend",
                            # EcsDeployAction consumes this file; without it the
                            # deploy action has no image to roll out.
                            'printf \'[{"name":"%s","imageUri":"%s"}]\''
                            " $CONTAINER_NAME"
                            " $ECR_REPO_URI:$CODEBUILD_RESOLVED_SOURCE_VERSION"
                            " > imagedefinitions.json",
                        ],
                    },
                },
                "artifacts": {
                    "base-directory": "backend",
                    "files": ["imagedefinitions.json"],
                },
            }),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,
            ),
            environment_variables={
                "ECR_REPO_URI": codebuild.BuildEnvironmentVariable(
                    value=ecr_repo.repository_uri
                ),
                "ECR_REGISTRY": codebuild.BuildEnvironmentVariable(
                    value=f"{self.account}.dkr.ecr.{self.region}.amazonaws.com"
                ),
                "CONTAINER_NAME": codebuild.BuildEnvironmentVariable(
                    value=container_name
                ),
            },
        )

        # Without this the build can authenticate but not push.
        ecr_repo.grant_pull_push(backend_build)

        frontend_build = codebuild.PipelineProject(
            self,
            "FrontendBuild",
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {"nodejs": "22"},
                        "commands": [
                            "cd frontend",
                            "npm ci",
                        ],
                    },
                    "build": {
                        "commands": [
                            "cd frontend",
                            "npm run lint",
                            # `npm run build` runs vue-tsc first, so a type
                            # error fails the pipeline rather than shipping.
                            "npm run build",
                        ],
                    },
                },
                "artifacts": {
                    "base-directory": "frontend/dist",
                    "files": ["**/*"],
                },
            }),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
            ),
        )

        # CodePipeline has no native CloudFront invalidation action, so a small
        # build project performs it after the S3 sync. Without it, returning
        # visitors keep the previous index.html until its TTL lapses.
        invalidation_project = codebuild.PipelineProject(
            self,
            "CacheInvalidation",
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "build": {
                        "commands": [
                            "aws cloudfront create-invalidation"
                            " --distribution-id $DISTRIBUTION_ID --paths '/*'",
                        ],
                    },
                },
            }),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
            ),
            environment_variables={
                "DISTRIBUTION_ID": codebuild.BuildEnvironmentVariable(
                    value=distribution.distribution_id
                ),
            },
        )
        invalidation_project.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudfront:CreateInvalidation"],
                resources=[
                    f"arn:aws:cloudfront::{self.account}:distribution/"
                    f"{distribution.distribution_id}"
                ],
            )
        )

        # enforce_ssl adds a topic policy denying any Publish over plain HTTP,
        # which resolves AwsSolutions-SNS3 outright rather than suppressing it.
        approval_topic = sns.Topic(
            self,
            "ApprovalTopic",
            display_name="Pipeline Approval",
            enforce_ssl=True,
        )

        stages = [
            codepipeline.StageProps(
                stage_name="Source",
                actions=[source_action],
            ),
            codepipeline.StageProps(
                stage_name="Build",
                actions=[
                    actions.CodeBuildAction(
                        action_name="BackendBuild",
                        project=backend_build,
                        input=source_output,
                        outputs=[backend_build_output],
                    ),
                    actions.CodeBuildAction(
                        action_name="FrontendBuild",
                        project=frontend_build,
                        input=source_output,
                        outputs=[frontend_build_output],
                    ),
                ],
            ),
        ]

        if is_production:
            stages.append(
                codepipeline.StageProps(
                    stage_name="Approve",
                    actions=[
                        actions.ManualApprovalAction(
                            action_name="ApproveProductionDeploy",
                            notification_topic=approval_topic,
                        ),
                    ],
                )
            )

        stages.append(
            codepipeline.StageProps(
                stage_name=f"Deploy-{env_config['environment'].capitalize()}",
                actions=[
                    # Backend and frontend deploy independently; neither waits
                    # on the other.
                    actions.EcsDeployAction(
                        action_name="DeployBackend",
                        service=service,
                        input=backend_build_output,
                        run_order=1,
                    ),
                    actions.S3DeployAction(
                        action_name="DeployFrontend",
                        bucket=frontend_bucket,
                        input=frontend_build_output,
                        extract=True,
                        run_order=1,
                    ),
                    actions.CodeBuildAction(
                        action_name="InvalidateCache",
                        project=invalidation_project,
                        input=frontend_build_output,
                        run_order=2,
                    ),
                ],
            )
        )

        pipeline = codepipeline.Pipeline(self, "Pipeline", stages=stages)

        # Environment/Service/Owner tags are applied once at the App in app.py and
        # propagate into this stack, so they are deliberately not repeated here.

        NagSuppressions.add_resource_suppressions(
            pipeline,
            [
                {
                    "id": "AwsSolutions-S1",
                    "reason": (
                        "The artifact bucket is created and owned by the CodePipeline "
                        "construct. It holds only build artifacts, is not internet "
                        "reachable, and every write to it is already recorded as a "
                        "pipeline execution — S3 access logs would add a second bucket "
                        "and no new information."
                    ),
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Wildcards are in CDK-generated policies for the pipeline and its "
                        "action roles. They are scoped to this pipeline's own artifact "
                        "bucket (s3:GetObject*/PutObject/DeleteObject/Abort* on "
                        "<bucket>/*), its own CodeBuild projects, and the frontend bucket "
                        "objects the S3 deploy action writes; the object keys are "
                        "generated per execution and cannot be enumerated in advance."
                    ),
                },
            ],
            apply_to_children=True,
        )

        for project in (backend_build, frontend_build, invalidation_project):
            NagSuppressions.add_resource_suppressions(
                project,
                [
                    {
                        "id": "AwsSolutions-CB4",
                        "reason": (
                            "Build artifacts are encrypted with the AWS-managed key for "
                            "CodeBuild. They contain only source code that is already in "
                            "a repository plus compiled output — no secrets — so a "
                            "customer-managed KMS key would add key rotation and cost for "
                            "no additional protection."
                        ),
                    },
                    {
                        "id": "AwsSolutions-IAM5",
                        "reason": (
                            "Wildcards are in the CDK-generated CodeBuild service role: "
                            "log streams under this project's own log group and report "
                            "groups under this project's own name, plus the ECR grant "
                            "whose ecr:GetAuthorizationToken is only valid on '*' per the "
                            "ECR API. All are created at build time and cannot be named "
                            "in advance."
                        ),
                    },
                ],
                apply_to_children=True,
            )
