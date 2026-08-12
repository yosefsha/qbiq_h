# `account` is the real AWS account, shared with production for now. See the
# note in prod.py: this is a simplification to unblock a single-account setup,
# not a recommendation.
#
# STILL A PLACEHOLDER — `domain_name` / `frontend_domain`. No `example.com`
# hosted zone exists in this account, so the lookup in frontend_stack.py is
# answered by a fake seeded entry in `cdk.json`. Synthesis succeeds; a real
# deploy would not. Set a real domain and delete the seeded `hosted-zone:` key
# before deploying (INF-06).
STAGING_CONFIG = {
    "environment": "staging",
    "account": "963352896991",
    "region": "us-east-1",
    "service_name": "myapp",
    "owner": "platform-team",
    "domain_name": "example.com",
    "frontend_domain": "staging.example.com",
    "backend_desired_count": 1,
    "backend_min_tasks": 1,
    "backend_max_tasks": 4,
    "github_owner": "yosefsha",
    "github_repo": "qbiq_h",
    "github_branch": "main",
    "codestar_connection_arn": "REPLACE_WITH_CODESTAR_CONNECTION_ARN",
}
