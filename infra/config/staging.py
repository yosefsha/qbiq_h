# NOTE: `account` is a deliberately fake 12-digit placeholder so that `cdk synth`
# runs offline. CDK requires a syntactically valid account id to build the
# environment-scoped lookup keys that `cdk.json` seeds with placeholder values
# (availability zones, hosted zone). Replace with the real staging account id
# before `cdk deploy`, and delete the matching seeded keys from `cdk.json` so the
# lookups resolve against the real account.
STAGING_CONFIG = {
    "environment": "staging",
    "account": "000000000000",
    "region": "us-east-1",
    "service_name": "myapp",
    "owner": "platform-team",
    "domain_name": "example.com",
    "frontend_domain": "staging.example.com",
    "backend_desired_count": 1,
    "backend_min_tasks": 1,
    "backend_max_tasks": 4,
    "github_owner": "REPLACE_WITH_GITHUB_OWNER",
    "github_repo": "REPLACE_WITH_GITHUB_REPO",
    "github_branch": "main",
    "codestar_connection_arn": "REPLACE_WITH_CODESTAR_CONNECTION_ARN",
}
