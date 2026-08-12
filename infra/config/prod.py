# `account` is the real AWS account. Staging and production currently share it,
# which is a deliberate simplification, not a recommendation: a compromised or
# misconfigured staging deploy can reach production resources. Split into two
# accounts before this carries anything of value.
#
# STILL A PLACEHOLDER — `domain_name` / `frontend_domain`. No `example.com`
# hosted zone exists in this account, which is why `custom_domain_enabled` is
# False: frontend_stack.py then skips `route53.HostedZone.from_lookup`, the ACM
# certificate and the Route 53 alias entirely, and the distribution serves on
# its generated `*.cloudfront.net` name. Requesting a DNS-validated certificate
# against a zone that does not exist would synthesize cleanly and never deploy,
# so the flag stays off until a real delegated domain exists. Set one, flip the
# flag, and the certificate and alias appear — see docs/runbook.md for what
# stays manual.
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
    "custom_domain_enabled": False,
    "backend_desired_count": 2,
    "backend_min_tasks": 2,
    "backend_max_tasks": 10,
    # Protocol the ALB listener speaks — one key, read by backend_stack.py to
    # build the listener and by frontend_stack.py for CloudFront's
    # OriginProtocolPolicy on the `/api/*` behaviour. They have to agree or the
    # edge answers 502 and nothing in the application log says why, which is
    # why this is a single setting rather than one on each side.
    # "HTTPS" switches the listener to 443 (plus an HTTP:80 listener that only
    # redirects) and requires `alb_certificate_arn` below. Production must not
    # be deployed on "HTTP": the session cookie would cross the public internet
    # between CloudFront and the ALB in clear.
    "alb_listener_protocol": "HTTP",
    # The ACM certificate the HTTPS listener presents. Empty because
    # `domain_name` above is a placeholder and a certificate cannot be issued
    # against a zone that does not exist. It must cover `frontend_domain`, not
    # the ALB's own *.elb.amazonaws.com name: CloudFront forwards the viewer's
    # Host header and uses it for SNI to this origin. See docs/runbook.md.
    "alb_certificate_arn": "",
    # Where CloudWatch alarms are sent. `None` creates the SNS topic with no
    # subscription — the alarms still fire and are still visible in the
    # console, but nobody is paged. Set a real address before relying on them.
    "alarm_email": None,
    # Application runtime settings injected into the task definition. They
    # match backend/app/settings.py's own defaults today; they are here so an
    # environment can differ without a code change.
    "cache_ttl_seconds": 300,
    "session_ttl_seconds": 1800,
    "log_level": "INFO",
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
