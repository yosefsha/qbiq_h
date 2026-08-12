# `account` is the real AWS account. Staging and production currently share it,
# which is a deliberate simplification, not a recommendation: a compromised or
# misconfigured staging deploy can reach production resources. Split into two
# accounts before this carries anything of value.
#
# STILL A PLACEHOLDER — `domain_name` / `frontend_domain`. No `example.com`
# hosted zone exists in this account, so `route53.HostedZone.from_lookup` in
# frontend_stack.py is answered by a fake seeded entry in `cdk.json`. Synthesis
# therefore succeeds while a real `cdk deploy` would fail against a zone id that
# does not exist. Set a real domain and delete the seeded `hosted-zone:` key
# before deploying (INF-06).
#
# `codestar_connection_arn` must be created and authorised by hand in the
# console — it cannot be provisioned by CDK (INF-07).
PROD_CONFIG = {
    "environment": "prod",
    "account": "150758095463",
    "region": "us-east-1",
    "service_name": "myapp",
    "owner": "platform-team",
    "domain_name": "example.com",
    "frontend_domain": "app.example.com",
    "backend_desired_count": 2,
    "backend_min_tasks": 2,
    "backend_max_tasks": 10,
    "github_owner": "yosefsha",
    "github_repo": "qbiq_h",
    "github_branch": "main",
    "codestar_connection_arn": "REPLACE_WITH_CODESTAR_CONNECTION_ARN",
}
