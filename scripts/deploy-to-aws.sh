#!/usr/bin/env bash
#
# qbiq_h — one-command AWS deployment.
#
#   ./scripts/deploy-to-aws.sh [staging|prod]      # defaults to staging
#
# Deploys the whole storefront from a clean account: the container registry, an
# image, the VPC, the data tier, the API service, the CDN — then migrates and
# seeds the database, uploads the SPA, and prints the URL to open.
#
# **This script has never been run.** No AWS credentials exist on the machine it
# was written on and nothing in this project has ever been deployed. Every AWS
# call below is written from the API contract and from `infra/stacks/*.py`, not
# from a live run. `docs/runbook.md` lists what a first real run still needs.
#
# It is written to be re-runnable: a second invocation is an update, not an
# error. Every `describe-stacks` read is guarded, every deploy is a `cdk deploy`
# (which is a no-op when nothing changed), and both one-off tasks — the Alembic
# migration and the catalogue seed — are idempotent by design.
#
# What this script deliberately is NOT: the steady-state deploy path. That is
# `.github/workflows/deploy.yml`, which runs on merge to `main` over OIDC with no
# stored credential (ADR-004). This script is for standing an environment up (or
# rebuilding one) from a laptop with real AWS credentials, and it is the only
# thing that can do the parts the workflow cannot: create infrastructure, and
# push the very first image into an empty registry.

set -euo pipefail

# The AWS CLI pipes anything long into a pager, which blocks a non-interactive
# script forever with no output.
export AWS_PAGER=""

# CloudFormation waits here run for tens of minutes; the defaults give up early.
export AWS_SDK_LOAD_CONFIG=1
export AWS_MAX_ATTEMPTS=10
export AWS_RETRY_MODE=adaptive

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

TOTAL_STEPS=9

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

ENVIRONMENT="${1:-staging}"

step() {
    printf '\n%b[%s/%s] %s%b\n' "$YELLOW" "$1" "$TOTAL_STEPS" "$2" "$NC"
}

info() { printf '%b%s%b\n' "$BLUE" "$1" "$NC"; }
ok() { printf '%b%s%b\n' "$GREEN" "$1" "$NC"; }
fail() {
    printf '%b%s%b\n' "$RED" "$1" "$NC" >&2
    exit 1
}

# `describe-stacks` on a stack that does not exist is an error, not an empty
# result, and this script has to cope with every stack being absent. Every read
# of a stack output goes through here, which returns "" instead of exploding.
stack_output() {
    local stack_name="$1" output_key="$2"
    aws cloudformation describe-stacks \
        --stack-name "$stack_name" \
        --region "$AWS_REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='${output_key}'].OutputValue" \
        --output text 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# [1/9] Preflight
# ---------------------------------------------------------------------------
# Everything that can be known to be wrong before a single resource is created
# is checked here, because the alternative is discovering it 20 minutes into an
# RDS deploy.
step 1 "Preflight checks"

case "$ENVIRONMENT" in
    staging | prod) ;;
    *)
        fail "Unknown environment '${ENVIRONMENT}'. Valid values: staging, prod.
Usage: ./scripts/deploy-to-aws.sh [staging|prod]"
        ;;
esac

# The CDK CLI is a Node package and is not in infra/requirements.txt. Prefer a
# globally installed one; fall back to npx so a clean machine still works.
if command -v cdk >/dev/null 2>&1; then
    CDK=(cdk)
else
    info "No 'cdk' on PATH — falling back to 'npx aws-cdk@2' (slower first run)."
    CDK=(npx --yes aws-cdk@2)
fi

# cdk.json runs a bare `python3`, so the venv has to be on PATH or synthesis
# fails with ModuleNotFoundError: No module named 'aws_cdk'. Activating it is
# not optional decoration.
if [ ! -x "$PROJECT_ROOT/.venv/bin/python3" ]; then
    fail "The CDK virtualenv is missing. Create it first:
  python3 -m venv .venv && .venv/bin/pip install -r infra/requirements.txt"
fi
# shellcheck source=/dev/null
source "$PROJECT_ROOT/.venv/bin/activate"

if ! python3 -c 'import aws_cdk' >/dev/null 2>&1; then
    fail "The CDK virtualenv exists but aws_cdk is not installed in it:
  .venv/bin/pip install -r infra/requirements.txt"
fi

# The account, region and service name come from infra/config/<env>.py — the
# same file the CDK app reads — so this script cannot deploy into an account the
# stacks were not configured for.
config_line=$(python3 - "$ENVIRONMENT" <<'PY'
import importlib
import sys

env = sys.argv[1]
sys.path.insert(0, "infra")
config = getattr(importlib.import_module(f"config.{env}"), f"{env.upper()}_CONFIG")
print(config["account"], config["region"], config["service_name"])
PY
)
read -r EXPECTED_ACCOUNT AWS_REGION SERVICE_NAME <<<"$config_line"

if ! CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text 2>&1); then
    fail "aws sts get-caller-identity failed:
${CALLER_ARN}

There are no usable AWS credentials in this shell. Configure a profile or export
AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN and try again."
fi
ACTUAL_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

if [ "$ACTUAL_ACCOUNT" != "$EXPECTED_ACCOUNT" ]; then
    fail "Wrong AWS account.
  credentials are for : ${ACTUAL_ACCOUNT}
  infra/config/${ENVIRONMENT}.py expects: ${EXPECTED_ACCOUNT}

Deploying into the wrong account would create a second copy of every resource
under names that look right. Switch profile, or fix 'account' in
infra/config/${ENVIRONMENT}.py."
fi

# Checked before the build rather than at it: `docker build` against a stopped
# daemon fails with a connection error four steps and several minutes in.
if ! docker info >/dev/null 2>&1; then
    fail "Docker is not running. Start Docker Desktop (or your daemon) and re-run."
fi

BACKEND_STACK="${ENVIRONMENT}-backend"
DEPLOY_STACK="${ENVIRONMENT}-deploy"
ECR_STACK="${ENVIRONMENT}-ecr"

GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
VERSION_TAG="${ENVIRONMENT}-${GIT_SHA}-${TIMESTAMP}"

printf '%b========================================%b\n' "$BLUE" "$NC"
printf '%bqbiq_h — AWS deployment%b\n' "$BLUE" "$NC"
printf '%bEnvironment : %s%b\n' "$BLUE" "$ENVIRONMENT" "$NC"
printf '%bAccount     : %s%b\n' "$BLUE" "$ACTUAL_ACCOUNT" "$NC"
printf '%bRegion      : %s%b\n' "$BLUE" "$AWS_REGION" "$NC"
printf '%bIdentity    : %s%b\n' "$BLUE" "$CALLER_ARN" "$NC"
printf '%bVersion tag : %s%b\n' "$BLUE" "$VERSION_TAG" "$NC"
printf '%b========================================%b\n' "$BLUE" "$NC"

if [ "$ENVIRONMENT" = "prod" ]; then
    printf '%bThis is PRODUCTION.%b\n' "$YELLOW" "$NC"
fi

ok "Preflight passed."

# ---------------------------------------------------------------------------
# [2/9] CDK bootstrap
# ---------------------------------------------------------------------------
# The assets these stacks synthesize need the CDK bootstrap bucket and roles.
# Bootstrapping is account/region-wide and only has to happen once, so this
# checks for the CDKToolkit stack rather than running it every time — it is
# idempotent, but it is also a minute of nothing on every deploy.
step 2 "CDK bootstrap"

if aws cloudformation describe-stacks --stack-name CDKToolkit \
    --region "$AWS_REGION" >/dev/null 2>&1; then
    ok "CDKToolkit already exists in ${ACTUAL_ACCOUNT}/${AWS_REGION} — skipping bootstrap."
else
    info "CDKToolkit not found — bootstrapping ${ACTUAL_ACCOUNT}/${AWS_REGION}."
    "${CDK[@]}" bootstrap "aws://${ACTUAL_ACCOUNT}/${AWS_REGION}" -c "env=${ENVIRONMENT}"
    ok "Bootstrapped."
fi

# ---------------------------------------------------------------------------
# [3/9] The container registry, on its own and first
# ---------------------------------------------------------------------------
# This is the whole reason infra/stacks/ecr_stack.py exists. The backend stack's
# task definitions pull `<repo>:latest`; if the repository were created by that
# same stack it would be empty at the moment its own ECS service tried to pull,
# the service would never stabilise, and CloudFormation would roll the deploy
# back after its timeout. Registry first, image second, everything else third.
step 3 "Deploy ${ECR_STACK} (container registry)"

"${CDK[@]}" deploy "$ECR_STACK" \
    --require-approval never \
    -c "env=${ENVIRONMENT}"

ECR_URI=$(stack_output "$ECR_STACK" "RepositoryUri")
if [ -z "$ECR_URI" ] || [ "$ECR_URI" = "None" ]; then
    fail "Could not read RepositoryUri from ${ECR_STACK}. The stack deployed but
published no such output — check infra/stacks/ecr_stack.py."
fi
ok "ECR repository: ${ECR_URI}"

# ---------------------------------------------------------------------------
# [4/9] Build and push the backend image
# ---------------------------------------------------------------------------
step 4 "Build and push the backend image"

# --platform linux/amd64 IS NOT OPTIONAL.
#
# The build host here is Apple Silicon (arm64) and Fargate in this project runs
# x86_64 — infra/stacks/backend_stack.py takes the default CPU architecture,
# which is X86_64. Without this flag Docker builds a native arm64 image that
# works perfectly on the developer's laptop, pushes without complaint, and then
# dies in ECS with `exec /usr/local/bin/uvicorn: exec format error` — a message
# that appears only in the task's CloudWatch stream, after the task has already
# been replaced. The service then never stabilises and the failure looks like a
# health-check problem rather than an architecture one.

# The local tag mirrors the repository name (`<service_name>-backend`, fixed in
# ecr_stack.py) so `docker images` on the build host reads the same as ECR does.
LOCAL_IMAGE="${SERVICE_NAME}-backend:${VERSION_TAG}"

docker build \
    --platform linux/amd64 \
    --pull \
    -t "$LOCAL_IMAGE" \
    "$PROJECT_ROOT/backend"

# `docker login` is idempotent and the token is short-lived, so this runs on
# every invocation rather than being cached. It takes the registry host, not the
# repository path — credentials are per-registry.
ECR_REGISTRY="${ECR_URI%%/*}"
aws ecr get-login-password --region "$AWS_REGION" |
    docker login --username AWS --password-stdin "$ECR_REGISTRY"

# Two tags, for two different jobs.
#
# `$VERSION_TAG` (env + git sha + timestamp) is the traceable one: it says
# exactly which commit is running, and it never moves, so it is what a rollback
# names.
#
# `latest` is the one the CDK task definitions reference (see the comment on
# `from_ecr_repository` in backend_stack.py). It has to exist before step 5, or
# the service and migration task definitions point at a tag that is not there.
docker tag "$LOCAL_IMAGE" "${ECR_URI}:${VERSION_TAG}"
docker tag "$LOCAL_IMAGE" "${ECR_URI}:latest"
docker push "${ECR_URI}:${VERSION_TAG}"
docker push "${ECR_URI}:latest"

ok "Pushed ${ECR_URI}:${VERSION_TAG}"
ok "Pushed ${ECR_URI}:latest"

# ---------------------------------------------------------------------------
# [5/9] The rest of the infrastructure
# ---------------------------------------------------------------------------
# One `cdk deploy` with every stack named: CDK orders them by their own
# dependencies (network -> data -> backend -> frontend, with deploy last), so
# the order in this array is documentation rather than instruction.
#
# `<env>-deploy` is included even though it deploys no application: it is the
# stack that publishes the cluster name, service name, migration task-definition
# family, private subnet ids, task security group, bucket and distribution id
# that steps 6-8 read. Deploying the environment without it would leave this
# script unable to run a migration, and would leave
# `.github/workflows/deploy.yml` without the role it assumes.
step 5 "Deploy infrastructure (network, data, backend, frontend, deploy)"

printf '%b%s%b\n' "$YELLOW" "Expect this to take 15-25 minutes. Most of it is \
${ENVIRONMENT}-data: an RDS instance and an ElastiCache replication group are \
both slow to create, and CloudFront in ${ENVIRONMENT}-frontend takes several \
minutes to propagate. A long silence here is normal, not a hang." "$NC"

"${CDK[@]}" deploy \
    "${ENVIRONMENT}-network" \
    "${ENVIRONMENT}-data" \
    "${ENVIRONMENT}-backend" \
    "${ENVIRONMENT}-frontend" \
    "$DEPLOY_STACK" \
    --require-approval never \
    -c "env=${ENVIRONMENT}"

ok "Infrastructure deployed."

# Everything the remaining steps need, read from the one stack that publishes it
# all. Renaming any of these outputs breaks this script and deploy.yml together,
# which is why deploy_stack.py calls the output keys a contract.
CLUSTER=$(stack_output "$DEPLOY_STACK" "EcsClusterName")
SERVICE=$(stack_output "$DEPLOY_STACK" "EcsServiceName")
MIGRATION_FAMILY=$(stack_output "$DEPLOY_STACK" "MigrationTaskDefinitionFamily")
MIGRATION_CONTAINER=$(stack_output "$DEPLOY_STACK" "MigrationContainerName")
SUBNET_IDS=$(stack_output "$DEPLOY_STACK" "DeploySubnetIds")
SECURITY_GROUP=$(stack_output "$DEPLOY_STACK" "DeploySecurityGroupId")
ASSIGN_PUBLIC_IP=$(stack_output "$DEPLOY_STACK" "DeployAssignPublicIp")
FRONTEND_BUCKET=$(stack_output "$DEPLOY_STACK" "FrontendBucketName")
DISTRIBUTION_ID=$(stack_output "$DEPLOY_STACK" "CloudFrontDistributionId")

for pair in \
    "EcsClusterName:${CLUSTER}" \
    "EcsServiceName:${SERVICE}" \
    "MigrationTaskDefinitionFamily:${MIGRATION_FAMILY}" \
    "MigrationContainerName:${MIGRATION_CONTAINER}" \
    "DeploySubnetIds:${SUBNET_IDS}" \
    "DeploySecurityGroupId:${SECURITY_GROUP}" \
    "DeployAssignPublicIp:${ASSIGN_PUBLIC_IP}" \
    "FrontendBucketName:${FRONTEND_BUCKET}" \
    "CloudFrontDistributionId:${DISTRIBUTION_ID}"; do
    if [ -z "${pair#*:}" ] || [ "${pair#*:}" = "None" ]; then
        fail "${DEPLOY_STACK} published no '${pair%%:*}' output. Something in
infra/stacks/deploy_stack.py changed without this script following it."
    fi
done

# ---------------------------------------------------------------------------
# [6/9] Migrate, then seed
# ---------------------------------------------------------------------------
# Both run as one-off Fargate tasks in the same subnets and the same security
# group the service's own tasks use, because that group is the only source the
# RDS ingress rule in backend_stack.py admits. Nothing on this laptop can reach
# the database, and that is by design.
#
# The subnets are public and the tasks take a public IP — read from the stack,
# never hardcoded here. That is a consequence of removing the NAT Gateway
# (network_stack.py): without egress a task cannot pull its image from ECR, and
# would stop before running a single command. Inbound is still restricted to the
# ALB security group; the public IP buys egress, not reachability.
#
# The migration task definition already points at `<repo>:latest`, which step 4
# just moved to the image built from this commit — so there is no revision to
# register here. The command is overridden anyway, so that what runs is visible
# at the call site rather than only in the CDK.
step 6 "Run database migrations, then seed the catalogue"

# `aws ecs run-task` returning 200 means the task was ACCEPTED, not that it
# succeeded — and not even that it started. A task can fail to pull its image,
# or exit 1 from a broken migration, and `run-task` reports neither. This
# function is the difference between "the deploy said it worked" and "the schema
# is at head": it waits for the task to stop and fails the script on any
# non-zero container exit code, and on a task that never produced one at all.
run_one_off_task() {
    local description="$1" command_json="$2" task_arn exit_code stopped_reason

    info "Starting one-off task: ${description}"

    task_arn=$(aws ecs run-task \
        --cluster "$CLUSTER" \
        --task-definition "$MIGRATION_FAMILY" \
        --launch-type FARGATE \
        --region "$AWS_REGION" \
        --started-by "deploy-script-${VERSION_TAG}" \
        --network-configuration \
        "awsvpcConfiguration={subnets=[${SUBNET_IDS}],securityGroups=[${SECURITY_GROUP}],assignPublicIp=${ASSIGN_PUBLIC_IP}}" \
        --overrides \
        "{\"containerOverrides\":[{\"name\":\"${MIGRATION_CONTAINER}\",\"command\":${command_json}}]}" \
        --query 'tasks[0].taskArn' \
        --output text)

    if [ -z "$task_arn" ] || [ "$task_arn" = "None" ]; then
        fail "ECS accepted no task for '${description}'. Check the 'failures'
array from: aws ecs run-task --cluster ${CLUSTER} --task-definition ${MIGRATION_FAMILY}"
    fi

    info "Task ${task_arn##*/} started; waiting for it to stop."

    # `wait tasks-stopped` polls for up to 10 minutes. A migration that needs
    # longer than that has bigger problems than this script, and a timeout here
    # exits non-zero rather than falling through to a green deploy.
    if ! aws ecs wait tasks-stopped \
        --cluster "$CLUSTER" --tasks "$task_arn" --region "$AWS_REGION"; then
        fail "Timed out waiting for '${description}' (task ${task_arn##*/}) to stop.
It may still be running. Check it before re-running this script:
  aws ecs describe-tasks --cluster ${CLUSTER} --tasks ${task_arn}"
    fi

    exit_code=$(aws ecs describe-tasks \
        --cluster "$CLUSTER" --tasks "$task_arn" --region "$AWS_REGION" \
        --query "tasks[0].containers[?name=='${MIGRATION_CONTAINER}'].exitCode | [0]" \
        --output text)
    stopped_reason=$(aws ecs describe-tasks \
        --cluster "$CLUSTER" --tasks "$task_arn" --region "$AWS_REGION" \
        --query 'tasks[0].stoppedReason' --output text)

    # An absent exit code is not a pass. It means the container never ran at all
    # — almost always CannotPullContainerError (wrong architecture, or a tag
    # that is not in the registry) or a networking failure reaching ECR.
    if [ -z "$exit_code" ] || [ "$exit_code" = "None" ]; then
        fail "'${description}' produced no container exit code, so it never ran.
Stopped reason: ${stopped_reason}
Logs: aws logs tail /aws/ecs/... --log-stream-name-prefix migrate"
    fi

    if [ "$exit_code" != "0" ]; then
        fail "'${description}' exited ${exit_code}.
Stopped reason: ${stopped_reason}
The service was NOT updated. Read the 'migrate' log stream in the backend log
group before re-running:
  aws logs describe-log-groups --log-group-name-prefix ${ENVIRONMENT}-backend"
    fi

    ok "${description} completed (exit 0)."
}

# Idempotent: `alembic upgrade head` is a no-op once the schema is at head, and
# app/seed.py upserts the catalogue rather than inserting it. Re-running this
# script is safe.
run_one_off_task "alembic upgrade head" '["alembic","upgrade","head"]'
run_one_off_task "python -m app.seed" '["python","-m","app.seed"]'

# ---------------------------------------------------------------------------
# [7/9] Build and upload the SPA
# ---------------------------------------------------------------------------
step 7 "Build the SPA and upload it to S3"

# `npm ci` and not `npm install`: the lockfile is the input, and a deploy is
# exactly the moment a silently-resolved dependency would matter. `npm run
# build` runs `vue-tsc -b` first, so a type error fails here rather than
# shipping.
(
    cd "$PROJECT_ROOT/frontend"
    npm ci
    npm run build
)

# `--delete` removes objects this build no longer produces. Vite emits
# content-hashed filenames, so that deletes the *previous* build's chunks: a
# visitor holding the old index.html can 404 on one until they reload. That
# window is one request wide because index.html is served with caching disabled
# (frontend_stack.py).
aws s3 sync "$PROJECT_ROOT/frontend/dist/" "s3://${FRONTEND_BUCKET}/" \
    --delete --region "$AWS_REGION"
ok "Uploaded to s3://${FRONTEND_BUCKET}/"

invalidation_id=$(aws cloudfront create-invalidation \
    --distribution-id "$DISTRIBUTION_ID" \
    --paths '/*' \
    --query 'Invalidation.Id' \
    --output text)
info "Invalidation ${invalidation_id} created; waiting for it to complete."
aws cloudfront wait invalidation-completed \
    --distribution-id "$DISTRIBUTION_ID" --id "$invalidation_id"
ok "CloudFront invalidated."

# ---------------------------------------------------------------------------
# [8/9] Force the service onto the new image
# ---------------------------------------------------------------------------
# The task definition references `latest`, and step 4 moved that tag. ECS does
# not notice on its own — a task definition is not re-resolved until a task
# starts — so without this the service keeps running whatever it pulled last.
#
# On a first deploy this is redundant (the service started after the push) and
# harmless. On every subsequent run it is the step that actually ships the code.
step 8 "Force a new ECS deployment"

aws ecs update-service \
    --cluster "$CLUSTER" \
    --service "$SERVICE" \
    --force-new-deployment \
    --region "$AWS_REGION" >/dev/null

info "Waiting for the service to stabilise (rolling deploy at 100%/200%)."
# backend_stack.py enables the deployment circuit breaker with rollback, so a
# release whose tasks never pass /health is reverted by ECS. Waiting is what
# makes this script notice that instead of printing a URL for a version that
# quietly rolled back.
if ! aws ecs wait services-stable \
    --cluster "$CLUSTER" --services "$SERVICE" --region "$AWS_REGION"; then
    fail "The ECS service did not stabilise. The circuit breaker may have rolled
back to the previous task set. Check the service events and the backend log
group:
  aws ecs describe-services --cluster ${CLUSTER} --services ${SERVICE} \\
    --query 'services[0].events[:10]'"
fi
ok "Service stable."

# ---------------------------------------------------------------------------
# [9/9] Where it is
# ---------------------------------------------------------------------------
step 9 "Deployment summary"

ALB_DNS=$(stack_output "$BACKEND_STACK" "LoadBalancerDnsName")
[ -n "$ALB_DNS" ] && [ "$ALB_DNS" != "None" ] || ALB_DNS="(unavailable)"

# The distribution's domain name is not a stack output — `frontend_stack.py`
# publishes none — so it is read from CloudFront itself. That also covers the
# custom-domain case: with `custom_domain_enabled` off this is the generated
# *.cloudfront.net name, which is the host actually serving the SPA today.
CLOUDFRONT_DOMAIN=$(aws cloudfront get-distribution \
    --id "$DISTRIBUTION_ID" \
    --query 'Distribution.DomainName' \
    --output text 2>/dev/null || echo "")
[ -n "$CLOUDFRONT_DOMAIN" ] && [ "$CLOUDFRONT_DOMAIN" != "None" ] ||
    CLOUDFRONT_DOMAIN="(unavailable)"

printf '\n%b========================================%b\n' "$GREEN" "$NC"
printf '%bDeployment complete — %s%b\n' "$GREEN" "$ENVIRONMENT" "$NC"
printf '%b========================================%b\n\n' "$GREEN" "$NC"

printf '%bOpen this:%b   https://%s\n' "$GREEN" "$NC" "$CLOUDFRONT_DOMAIN"
printf '%bALB (API):%b   http://%s\n' "$GREEN" "$NC" "$ALB_DNS"
printf '%bVersion:%b     %s\n' "$GREEN" "$NC" "$VERSION_TAG"
printf '%bGit commit:%b  %s\n' "$GREEN" "$NC" "$GIT_SHA"
printf '%bImage:%b       %s:%s\n' "$GREEN" "$NC" "$ECR_URI" "$VERSION_TAG"
printf '%bCluster:%b     %s / %s\n' "$GREEN" "$NC" "$CLUSTER" "$SERVICE"

printf '\n%bThe ALB is reachable directly and speaks plain HTTP; the CloudFront\n'  "$YELLOW"
printf 'URL above is the one to use. See docs/runbook.md for what is still\n'
printf 'manual — the ACM certificate, the custom domain, and the alarm email.%b\n' "$NC"
