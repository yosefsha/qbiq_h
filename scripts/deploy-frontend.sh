#!/usr/bin/env bash
#
# qbiq_h — deploy the SPA, and nothing else.
#
#   ./scripts/deploy-frontend.sh [staging|prod]     # defaults to staging
#
# Step 7 of scripts/deploy-to-aws.sh, on its own: build the SPA, sync it to the
# environment's bucket, invalidate CloudFront, wait for the invalidation. Step 8
# there — "Force a new ECS deployment" — is not part of this and is not missing
# from it: it exists because step 4 moves the `latest` tag, and nothing here
# builds or pushes an image.
#
# **This deploys a frontend-only change.** Nothing here builds an image, pushes
# to ECR, registers a task definition, runs migrations, seeds the catalogue or
# touches the ECS service. A change to anything under backend/ will appear to
# deploy successfully here and have no effect whatsoever — use
# scripts/deploy-to-aws.sh for that.
#
# It also cannot create infrastructure. The bucket and distribution are read
# from the <env>-deploy stack's outputs, so the environment has to be standing
# already; if it is not, this fails with that as the message rather than
# uploading into nothing.
#
# Safe to re-run: the sync is idempotent by content, and a second invalidation
# of a path that is already fresh is a no-op that costs nothing.

set -euo pipefail

export AWS_PAGER=""
export AWS_SDK_LOAD_CONFIG=1
export AWS_MAX_ATTEMPTS=10
export AWS_RETRY_MODE=adaptive

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

TOTAL_STEPS=4

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
# result. Returning "" instead lets the caller give a useful message.
stack_output() {
    local stack_name="$1" output_key="$2"
    aws cloudformation describe-stacks \
        --stack-name "$stack_name" \
        --region "$AWS_REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='${output_key}'].OutputValue" \
        --output text 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# [1/4] Preflight
# ---------------------------------------------------------------------------
step 1 "Preflight checks"

case "$ENVIRONMENT" in
    staging | prod) ;;
    *)
        fail "Unknown environment '${ENVIRONMENT}'. Valid values: staging, prod.
Usage: ./scripts/deploy-frontend.sh [staging|prod]"
        ;;
esac

command -v npm >/dev/null 2>&1 || fail "npm is not on PATH. Node 22 is what the build image uses."
command -v aws >/dev/null 2>&1 || fail "The AWS CLI is not on PATH."

# The account and region come from infra/config/<env>.py — the same file the CDK
# app reads — so this cannot upload into an account the stacks were never
# deployed to. python3 rather than parsing the file: it is the only reader that
# cannot disagree with CDK about what the config says.
config_line=$(python3 - "$ENVIRONMENT" <<'PY'
import importlib
import sys

env = sys.argv[1]
sys.path.insert(0, "infra")
config = getattr(importlib.import_module(f"config.{env}"), f"{env.upper()}_CONFIG")
print(config["account"], config["region"])
PY
)
read -r EXPECTED_ACCOUNT AWS_REGION <<<"$config_line"

if ! CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text 2>&1); then
    fail "aws sts get-caller-identity failed:
${CALLER_ARN}

There are no usable AWS credentials in this shell."
fi
ACTUAL_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

if [ "$ACTUAL_ACCOUNT" != "$EXPECTED_ACCOUNT" ]; then
    fail "Wrong AWS account.
  credentials are for : ${ACTUAL_ACCOUNT}
  infra/config/${ENVIRONMENT}.py expects: ${EXPECTED_ACCOUNT}

Switch profile, or fix 'account' in infra/config/${ENVIRONMENT}.py."
fi

DEPLOY_STACK="${ENVIRONMENT}-deploy"
FRONTEND_BUCKET=$(stack_output "$DEPLOY_STACK" "FrontendBucketName")
DISTRIBUTION_ID=$(stack_output "$DEPLOY_STACK" "CloudFrontDistributionId")

if [ -z "$FRONTEND_BUCKET" ] || [ "$FRONTEND_BUCKET" = "None" ] ||
    [ -z "$DISTRIBUTION_ID" ] || [ "$DISTRIBUTION_ID" = "None" ]; then
    fail "Could not read the bucket and distribution from '${DEPLOY_STACK}'.

That stack is where they are published, so this usually means the environment
is not standing yet. Stand it up first:
  ./scripts/deploy-to-aws.sh ${ENVIRONMENT}"
fi

GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

printf '\n%b========================================%b\n' "$GREEN" "$NC"
printf '%bFrontend deploy — %s%b\n' "$GREEN" "$ENVIRONMENT" "$NC"
printf '%b========================================%b\n\n' "$GREEN" "$NC"
printf '%bAccount     : %s%b\n' "$BLUE" "$ACTUAL_ACCOUNT" "$NC"
printf '%bRegion      : %s%b\n' "$BLUE" "$AWS_REGION" "$NC"
printf '%bBucket      : %s%b\n' "$BLUE" "$FRONTEND_BUCKET" "$NC"
printf '%bDistribution: %s%b\n' "$BLUE" "$DISTRIBUTION_ID" "$NC"
printf '%bGit commit  : %s%b\n' "$BLUE" "$GIT_SHA" "$NC"

if [ -n "$(git status --porcelain frontend/ 2>/dev/null)" ]; then
    printf '\n%bWARNING: frontend/ has uncommitted changes. You are about to deploy\n' "$YELLOW"
    printf 'a build of your working tree, not of %s.%b\n' "$GIT_SHA" "$NC"
fi

# ---------------------------------------------------------------------------
# [2/4] Build
# ---------------------------------------------------------------------------
step 2 "Build the SPA"

# `npm ci` and not `npm install`: the lockfile is the input, and a deploy is
# exactly the moment a silently-resolved dependency would matter. `npm run
# build` is `vue-tsc -b && vite build`, so a type error fails here rather than
# reaching the bucket. Tests and lint are CI's job, not this script's.
(
    cd "$PROJECT_ROOT/frontend"
    npm ci
    npm run build
)

[ -f "$PROJECT_ROOT/frontend/dist/index.html" ] ||
    fail "The build produced no frontend/dist/index.html. Nothing to upload."

ok "Built frontend/dist."

# ---------------------------------------------------------------------------
# [3/4] Upload
# ---------------------------------------------------------------------------
step 3 "Upload to s3://${FRONTEND_BUCKET}"

# `--delete` removes objects this build no longer produces. Vite emits
# content-hashed filenames, so without it every chunk of every past build
# accumulates forever. The window it opens is one request wide: a visitor
# holding the previous index.html can 404 on a deleted chunk, and index.html is
# served with caching disabled so they re-fetch immediately.
#
# It is also why nothing may be uploaded to this bucket out of band — anything
# the build did not produce is deleted on the next run. Product thumbnails live
# in frontend/public/ for exactly that reason, so they ship inside dist/.
aws s3 sync "$PROJECT_ROOT/frontend/dist/" "s3://${FRONTEND_BUCKET}/" \
    --delete --region "$AWS_REGION"

ok "Uploaded to s3://${FRONTEND_BUCKET}/"

# ---------------------------------------------------------------------------
# [4/4] Invalidate
# ---------------------------------------------------------------------------
step 4 "Invalidate CloudFront and wait"

# `/*` rather than a list of changed paths. index.html is the same key with new
# content on every deploy, and the /assets/* behaviour caches for a year, so a
# targeted invalidation is a chance to miss one. Invalidations are free up to
# 1,000 paths a month and `/*` counts as one path.
invalidation_id=$(aws cloudfront create-invalidation \
    --distribution-id "$DISTRIBUTION_ID" \
    --paths '/*' \
    --query 'Invalidation.Id' \
    --output text)

info "Invalidation ${invalidation_id} created; waiting for it to complete."

# Waited on rather than fired and forgotten: without this the script reports
# success while viewers are still being served the previous bundle, which is
# indistinguishable from the deploy not having worked.
aws cloudfront wait invalidation-completed \
    --distribution-id "$DISTRIBUTION_ID" --id "$invalidation_id"

ok "Invalidation complete."

CLOUDFRONT_DOMAIN=$(aws cloudfront get-distribution \
    --id "$DISTRIBUTION_ID" \
    --query 'Distribution.DomainName' \
    --output text 2>/dev/null || echo "")

ALIAS=$(aws cloudfront get-distribution \
    --id "$DISTRIBUTION_ID" \
    --query 'Distribution.DistributionConfig.Aliases.Items[0]' \
    --output text 2>/dev/null || echo "")

printf '\n%b========================================%b\n' "$GREEN" "$NC"
printf '%bFrontend deployed — %s%b\n' "$GREEN" "$ENVIRONMENT" "$NC"
printf '%b========================================%b\n\n' "$GREEN" "$NC"

if [ -n "$ALIAS" ] && [ "$ALIAS" != "None" ]; then
    printf '%bOpen this:%b   https://%s\n' "$GREEN" "$NC" "$ALIAS"
fi
if [ -n "$CLOUDFRONT_DOMAIN" ] && [ "$CLOUDFRONT_DOMAIN" != "None" ]; then
    printf '%bDirect:%b      https://%s\n' "$GREEN" "$NC" "$CLOUDFRONT_DOMAIN"
fi
printf '%bGit commit:%b  %s\n' "$GREEN" "$NC" "$GIT_SHA"

printf '\n%bHard-reload (Cmd+Shift+R) to check it: a normal reload can serve the\n' "$YELLOW"
printf 'previous bundle from the browser cache, which reads as a failed deploy.%b\n' "$NC"
