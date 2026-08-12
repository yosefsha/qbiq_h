#!/usr/bin/env python3
import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from config.prod import PROD_CONFIG
from config.staging import STAGING_CONFIG
from stacks.network_stack import NetworkStack
from stacks.data_stack import DataStack
from stacks.ecr_stack import EcrStack
from stacks.backend_stack import (
    CONTAINER_NAME,
    MIGRATION_CONTAINER_NAME,
    BackendStack,
)
from stacks.frontend_stack import FrontendStack
from stacks.deploy_stack import DeployStack

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

# The container registry, alone and first. It references nothing — no VPC, no
# data tier — so it can be deployed into an empty account before anything else
# exists, which is the whole point: the backend stack's task definitions pull
# `<repo>:latest`, so an image has to be pushed between this stack and that one.
# See ecr_stack.py, and scripts/deploy-to-aws.sh for the order in practice.
ecr = EcrStack(app, f"{target_env}-ecr", env=aws_env, env_config=env_config)

# References run in one direction only: backend -> data, and backend -> ecr. The
# backend stack reads the data stack's endpoints, secrets and security groups,
# and owns the ingress rules that let its tasks in. Nothing in the data stack or
# the ECR stack refers back to the backend stack — that would be the
# `DependencyCycle` the network stack's comment describes.
backend = BackendStack(
    app,
    f"{target_env}-backend",
    env=aws_env,
    env_config=env_config,
    vpc=network.vpc,
    ecr_repo=ecr.repository,
    data_environment=data.task_environment,
    data_secrets=data.task_secrets,
    data_client_targets=data.client_targets,
)

# Same one-way rule again: frontend -> backend. The frontend stack needs the
# ALB behind the CloudFront `/api/*` behavior, which is what keeps the SPA and
# the API on one origin (ADR-001). It reads the load balancer's DNS name and
# nothing in the backend stack refers to the frontend, so the reference is a
# plain cross-stack export. Passing anything the other way — a distribution
# domain into the backend's ALLOWED_ORIGINS, say — would close the loop into the
# `DependencyCycle` the network stack's comment describes; the same-origin design
# is exactly what makes that unnecessary.
frontend = FrontendStack(
    app,
    f"{target_env}-frontend",
    env=aws_env,
    env_config=env_config,
    load_balancer=backend.service.load_balancer,
)

# The deploy stack holds direct references to this environment's ECS service, S3
# bucket and CloudFront distribution, so it is environment-scoped and must carry
# an environment-prefixed name. A fixed name would make `cdk deploy -c env=staging`
# and `-c env=prod` target one CloudFormation stack, each silently reconfiguring
# the other's deploy role in place.
#
# It replaces the CodePipeline stack that used to sit here — the reasoning is in
# ADR-004. What is left is the IAM half of the deploy: a trust in GitHub's OIDC
# issuer and one least-privilege role, plus the outputs
# `.github/workflows/deploy.yml` reads so that nothing about this environment is
# hardcoded in YAML. The build and the ordering live in the workflow.
DeployStack(
    app,
    f"{target_env}-deploy",
    env=aws_env,
    env_config=env_config,
    vpc=network.vpc,
    # Straight from the ECR stack rather than via the backend stack, so this is
    # one edge (deploy -> ecr) instead of a reference that only looks like it
    # belongs to the backend. The `EcrRepositoryUri` output this produces is
    # unchanged, so .github/workflows/deploy.yml needs no edit.
    ecr_repo=ecr.repository,
    service=backend.service.service,
    task_definition=backend.service.task_definition,
    container_name=CONTAINER_NAME,
    migration_task_definition=backend.migration_task_definition,
    migration_container_name=MIGRATION_CONTAINER_NAME,
    task_security_group=backend.task_security_group,
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
