from aws_cdk import Stack
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_codepipeline as codepipeline
from aws_cdk import aws_codepipeline_actions as actions
from aws_cdk import aws_sns as sns
from cdk_nag import NagSuppressions
from constructs import Construct


class PipelineStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, env_config: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

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

        backend_build = codebuild.PipelineProject(
            self,
            "BackendBuild",
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {"python": "3.12"},
                        "commands": ["pip install -r requirements.txt"],
                    },
                    "pre_build": {
                        "commands": ["pytest"],
                    },
                    "build": {
                        "commands": [
                            "docker build -t $ECR_REPO_URI:$CODEBUILD_RESOLVED_SOURCE_VERSION .",
                            "aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_REPO_URI",
                            "docker push $ECR_REPO_URI:$CODEBUILD_RESOLVED_SOURCE_VERSION",
                        ],
                    },
                },
            }),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,
            ),
        )

        frontend_build = codebuild.PipelineProject(
            self,
            "FrontendBuild",
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {"nodejs": "20"},
                        "commands": ["npm ci"],
                    },
                    "build": {
                        "commands": [
                            "npm run lint",
                            "npm run build",
                        ],
                    },
                },
                "artifacts": {
                    "base-directory": "dist",
                    "files": ["**/*"],
                },
            }),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
            ),
        )

        # enforce_ssl adds a topic policy denying any Publish over plain HTTP,
        # which resolves AwsSolutions-SNS3 outright rather than suppressing it.
        approval_topic = sns.Topic(
            self,
            "ApprovalTopic",
            display_name="Pipeline Approval",
            enforce_ssl=True,
        )

        pipeline = codepipeline.Pipeline(
            self,
            "Pipeline",
            stages=[
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
                codepipeline.StageProps(
                    stage_name="Deploy-Staging",
                    actions=[
                        actions.ManualApprovalAction(
                            action_name="PromoteToProd",
                            notification_topic=approval_topic,
                            run_order=1,
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Deploy-Prod",
                    actions=[
                        actions.ManualApprovalAction(
                            action_name="ProdApproval",
                            notification_topic=approval_topic,
                        ),
                    ],
                ),
            ],
        )

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
                        "<bucket>/*) and to its own CodeBuild projects; the object keys "
                        "are generated per execution and therefore cannot be enumerated "
                        "in advance."
                    ),
                },
            ],
            apply_to_children=True,
        )

        for project in (backend_build, frontend_build):
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
                            "groups under this project's own name. Both are created at "
                            "build time and cannot be named in advance."
                        ),
                    },
                ],
                apply_to_children=True,
            )
