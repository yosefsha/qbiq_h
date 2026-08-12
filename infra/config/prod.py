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
#
# Context lookups (availability zones, hosted zone) are SEEDED in cdk.json
# rather than resolved live, because no credentials on the machine this was set
# up from reach this account. The seeded AZs are us-east-1a/1b. Delete those
# seeds and re-synth from a session that can assume the CDK lookup role in this
# account to replace them with real values — AZ names map to different physical
# zones per account, so the seeds are a placeholder, not a fact.
PROD_CONFIG = {
    "environment": "prod",
    "account": "963352896991",
    "region": "us-east-1",
    "service_name": "myapp",
    "owner": "platform-team",
    "domain_name": "example.com",
    "frontend_domain": "app.example.com",
    "backend_desired_count": 2,
    "backend_min_tasks": 2,
    "backend_max_tasks": 10,
    # Data tier. Multi-AZ, two weeks of backups and deletion protection are what
    # let data_stack.py leave the corresponding cdk-nag rules unsuppressed here —
    # staging suppresses them by name and says so.
    "db_instance_type": "t4g.medium",
    "db_allocated_storage": 50,
    "db_max_allocated_storage": 500,
    "db_backup_retention_days": 14,
    "db_multi_az": True,
    "db_deletion_protection": True,
    "cache_node_type": "cache.t4g.small",
    "cache_replicas": 2,
    "cache_snapshot_retention_days": 7,
    "github_owner": "yosefsha",
    "github_repo": "qbiq_h",
    "github_branch": "main",
    "codestar_connection_arn": "REPLACE_WITH_CODESTAR_CONNECTION_ARN",
}
