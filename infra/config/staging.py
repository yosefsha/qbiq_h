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
    # Data tier. Staging is deliberately smaller and cheaper than production:
    # single-AZ, one day of backups, no deletion protection. Every one of those
    # choices is a cdk-nag finding suppressed by name in data_stack.py, with the
    # production value it differs from spelled out in the reason.
    #
    # `cdk synth` emits a CloudFormation-Validate WARNING that this class "is not
    # valid for Engine 'postgres' EngineVersion '16.8'". It is stale validator
    # data — RDS has supported db.t4g on PostgreSQL since 13.x, and the same
    # warning appears for db.t3.micro. Left as is rather than downgrading the
    # engine to silence a false alarm.
    "db_instance_type": "t4g.micro",
    "db_allocated_storage": 20,
    "db_max_allocated_storage": 50,
    "db_backup_retention_days": 1,
    "db_multi_az": False,
    "db_deletion_protection": False,
    "cache_node_type": "cache.t4g.micro",
    # One replica, so automatic failover has somewhere to fail over to. Below
    # this the replication group cannot enable failover at all, which would make
    # staging unable to exercise the property ADR-003 chose Redis for.
    "cache_replicas": 1,
    "cache_snapshot_retention_days": 1,
    "github_owner": "yosefsha",
    "github_repo": "qbiq_h",
    "github_branch": "main",
    "codestar_connection_arn": "REPLACE_WITH_CODESTAR_CONNECTION_ARN",
}
