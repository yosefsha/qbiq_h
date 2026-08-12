#!/usr/bin/env bash
#
# qbiq_h — tear an AWS environment down.
#
#   ./scripts/destroy-aws.sh [staging|prod]        # defaults to staging
#
# The inverse of scripts/deploy-to-aws.sh: `cdk destroy` in reverse dependency
# order, so nothing is deleted while something else still references it.
#
# **This script has never been run**, like its counterpart — nothing in this
# project has ever been deployed.
#
# It does NOT delete everything, and the difference matters financially. Read
# the warning it prints before typing the confirmation.

set -euo pipefail

export AWS_PAGER=""
export AWS_SDK_LOAD_CONFIG=1
export AWS_MAX_ATTEMPTS=10
export AWS_RETRY_MODE=adaptive

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

ENVIRONMENT="${1:-staging}"

info() { printf '%b%s%b\n' "$BLUE" "$1" "$NC"; }
ok() { printf '%b%s%b\n' "$GREEN" "$1" "$NC"; }
fail() {
    printf '%b%s%b\n' "$RED" "$1" "$NC" >&2
    exit 1
}

case "$ENVIRONMENT" in
    staging | prod) ;;
    *)
        fail "Unknown environment '${ENVIRONMENT}'. Valid values: staging, prod.
Usage: ./scripts/destroy-aws.sh [staging|prod]"
        ;;
esac

if command -v cdk >/dev/null 2>&1; then
    CDK=(cdk)
else
    info "No 'cdk' on PATH — falling back to 'npx aws-cdk@2'."
    CDK=(npx --yes aws-cdk@2)
fi

if [ ! -x "$PROJECT_ROOT/.venv/bin/python3" ]; then
    fail "The CDK virtualenv is missing. Create it first:
  python3 -m venv .venv && .venv/bin/pip install -r infra/requirements.txt"
fi
# shellcheck source=/dev/null
source "$PROJECT_ROOT/.venv/bin/activate"

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

if ! ACTUAL_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>&1); then
    fail "aws sts get-caller-identity failed:
${ACTUAL_ACCOUNT}"
fi

if [ "$ACTUAL_ACCOUNT" != "$EXPECTED_ACCOUNT" ]; then
    fail "Wrong AWS account.
  credentials are for : ${ACTUAL_ACCOUNT}
  infra/config/${ENVIRONMENT}.py expects: ${EXPECTED_ACCOUNT}"
fi

printf '%b========================================%b\n' "$RED" "$NC"
printf '%bDESTROY — %s (%s / %s)%b\n' "$RED" "$ENVIRONMENT" "$ACTUAL_ACCOUNT" "$AWS_REGION" "$NC"
printf '%b========================================%b\n\n' "$RED" "$NC"

cat <<WARNING
This deletes the VPC, the ECS service and its load balancer, the CloudFront
distribution, and the ElastiCache replication group for '${ENVIRONMENT}'.

WHAT SURVIVES, AND KEEPS BILLING YOU:

  * The RDS database. Its removal policy is RETAIN in production and SNAPSHOT in
    staging (infra/stacks/data_stack.py), so 'cdk destroy' never actually
    deletes your data:
      - prod:    the DB instance itself is retained and continues to cost the
                 full hourly instance price, exactly as if you had not run this.
                 It also has deletion protection on, so even a manual delete is
                 refused until you turn that off.
      - staging: the instance is deleted but a FINAL SNAPSHOT is retained, and
                 snapshot storage is billed per GB-month for as long as it
                 exists. It is not free, and nothing here will ever remove it.
    Deleting either is a deliberate, separate act:
      aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier'
      aws rds describe-db-snapshots --snapshot-type manual

  * The ECR repository (RETAIN) and every image in it.
  * The S3 bucket holding the built SPA (RETAIN) and its objects.
  * Any ElastiCache final snapshot, on the same terms as the RDS one.

So "destroyed" here means "the compute and the network are gone". The stateful
things are still there, still on your bill, and are your call to remove.
WARNING

CONFIRMATION="destroy ${ENVIRONMENT}"
printf '\n%bType exactly: %s%b\n' "$YELLOW" "$CONFIRMATION" "$NC"
printf '> '
read -r typed

if [ "$typed" != "$CONFIRMATION" ]; then
    fail "Confirmation did not match. Nothing was destroyed."
fi

# Reverse of the deploy order. CDK works out the dependencies itself, but naming
# them in this order means a partial failure stops at the most-dependent stack
# still standing rather than half way down.
#
# `<env>-ecr` is destroyed last and is close to a no-op: the repository is RETAIN,
# so what goes away is the CloudFormation stack, not the registry or the images.
# It is included so a re-deploy starts from a clean stack rather than adopting a
# half-torn-down one.
STACKS=(
    "${ENVIRONMENT}-deploy"
    "${ENVIRONMENT}-frontend"
    "${ENVIRONMENT}-backend"
    "${ENVIRONMENT}-data"
    "${ENVIRONMENT}-network"
    "${ENVIRONMENT}-ecr"
)

for stack in "${STACKS[@]}"; do
    # Guarded: destroying an environment that was never fully deployed, or
    # re-running this after a partial failure, must not be an error.
    if ! aws cloudformation describe-stacks --stack-name "$stack" \
        --region "$AWS_REGION" >/dev/null 2>&1; then
        info "${stack} does not exist — skipping."
        continue
    fi

    printf '\n%bDestroying %s...%b\n' "$YELLOW" "$stack" "$NC"
    "${CDK[@]}" destroy "$stack" --force -c "env=${ENVIRONMENT}"
    ok "${stack} destroyed."
done

printf '\n%b========================================%b\n' "$GREEN" "$NC"
printf '%bTeardown complete — %s%b\n' "$GREEN" "$ENVIRONMENT" "$NC"
printf '%b========================================%b\n' "$GREEN" "$NC"
printf '\n%bThe RDS instance or its final snapshot, the ECR repository and the\n' "$YELLOW"
printf 'SPA bucket are still there and still billing. See the warning above.%b\n' "$NC"
