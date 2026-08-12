#!/usr/bin/env python3
import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from config.prod import PROD_CONFIG
from config.staging import STAGING_CONFIG
from stacks.network_stack import NetworkStack
from stacks.data_stack import DataStack
from stacks.backend_stack import CONTAINER_NAME, BackendStack
from stacks.frontend_stack import FrontendStack
from stacks.pipeline_stack import PipelineStack

app = cdk.App()

target_env = app.node.try_get_context("env") or "staging"
env_config = PROD_CONFIG if target_env == "prod" else STAGING_CONFIG

aws_env = cdk.Environment(
    account=env_config["account"],
    region=env_config["region"],
)

network = NetworkStack(app, f"{target_env}-network", env=aws_env, env_config=env_config)

data = DataStack(
    app,
    f"{target_env}-data",
    env=aws_env,
    env_config=env_config,
    vpc=network.vpc,
)

# References run in one direction only: backend -> data. The backend stack reads
# the data stack's endpoints, secrets and security groups, and owns the ingress
# rules that let its tasks in. Nothing in the data stack refers back to the
# backend stack — that would be the `DependencyCycle` the network stack's
# comment describes.
backend = BackendStack(
    app,
    f"{target_env}-backend",
    env=aws_env,
    env_config=env_config,
    vpc=network.vpc,
    data_environment=data.task_environment,
    data_secrets=data.task_secrets,
    data_client_targets=data.client_targets,
)

frontend = FrontendStack(app, f"{target_env}-frontend", env=aws_env, env_config=env_config)

# The pipeline holds direct references to this environment's ECS service, S3
# bucket and CloudFront distribution, so it is environment-scoped and must carry
# an environment-prefixed name. A fixed name would make `cdk deploy -c env=staging`
# and `-c env=prod` target one CloudFormation stack, each silently reconfiguring
# the other's pipeline in place.
PipelineStack(
    app,
    f"{target_env}-pipeline",
    env=aws_env,
    env_config=env_config,
    ecr_repo=backend.ecr_repo,
    service=backend.service.service,
    container_name=CONTAINER_NAME,
    frontend_bucket=frontend.bucket,
    distribution=frontend.distribution,
)

# Tagging is applied once, at the App, so every stack — including stacks added
# later by INF-04..INF-07 — inherits it without having to remember to opt in.
# CDK propagates App-level tags down to every taggable resource in every stack.
cdk.Tags.of(app).add("Environment", env_config["environment"])
cdk.Tags.of(app).add("Service", env_config["service_name"])
cdk.Tags.of(app).add("Owner", env_config["owner"])

cdk.Aspects.of(app).add(AwsSolutionsChecks())

app.synth()
