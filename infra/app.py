#!/usr/bin/env python3
import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from config.prod import PROD_CONFIG
from config.staging import STAGING_CONFIG
from stacks.network_stack import NetworkStack
from stacks.backend_stack import BackendStack
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

backend = BackendStack(
    app,
    f"{target_env}-backend",
    env=aws_env,
    env_config=env_config,
    vpc=network.vpc,
)

frontend = FrontendStack(app, f"{target_env}-frontend", env=aws_env, env_config=env_config)

PipelineStack(
    app,
    "ci-cd-pipeline",
    env=aws_env,
    env_config=env_config,
)

# Tagging is applied once, at the App, so every stack — including stacks added
# later by INF-04..INF-07 — inherits it without having to remember to opt in.
# CDK propagates App-level tags down to every taggable resource in every stack.
cdk.Tags.of(app).add("Environment", env_config["environment"])
cdk.Tags.of(app).add("Service", env_config["service_name"])
cdk.Tags.of(app).add("Owner", env_config["owner"])

cdk.Aspects.of(app).add(AwsSolutionsChecks())

app.synth()
