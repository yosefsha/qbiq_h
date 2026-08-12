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
# Deploys run from GitHub Actions over OIDC (ADR-004), so there is no CodeStar
# connection to authorise by hand any more. What replaced it is on the GitHub
# side: the `production` environment's required reviewers and deployment-branch
# policy, and the `AWS_ACCOUNT_ID` repository variable — see docs/runbook.md.
#
# Context lookups used to be SEEDED by hand in cdk.json, because no credentials
# on the machine this was set up from reached this account. Both seeds are gone:
# availability zones now resolve live and are cached in cdk.context.json (commit
# that file — it is what keeps CI synthing the same values), and the hosted-zone
# seed was a forged zone id for a domain nobody owns, read only when
# `custom_domain_enabled` is True, which it is not in either environment.
# Turning that flag on means owning a real domain and letting
# `HostedZone.from_lookup` resolve it — never re-seeding a value by hand.
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
    # be deployed on "HTTP": the session cookie would cross the CloudFront->ALB
    # hop in clear. That is enforced, not merely asserted — `backend_stack.py`
    # refuses to synthesize production on HTTP once `custom_domain_enabled` is
    # True, which is the point at which a certificate can actually be issued.
    # It stays "HTTP" here only because this environment has no delegated zone
    # yet, and so cannot have a certificate either.
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
    # Deploys come from GitHub Actions over OIDC, not from CodePipeline — see
    # ADR-004. These keys are the whole of what the deploy role trusts.
    "github_owner": "yosefsha",
    "github_repo": "qbiq_h",
    # Deployment branch. The trust policy cannot enforce it (one OIDC token
    # carries one `sub`, and a job that declares an environment stops presenting
    # the ref), so this value is what the GitHub environment's deployment-branch
    # policy must be set to by hand — see docs/runbook.md.
    "github_branch": "main",
    # The GitHub *environment* whose name appears in the OIDC subject claim:
    # `repo:yosefsha/qbiq_h:environment:production`. It must match the
    # `environment:` key on the production jobs in
    # .github/workflows/deploy.yml. This is also where the human gate lives: the
    # required-reviewer rule is a property of the GitHub environment, not of the
    # workflow, so it has to be configured in repository settings — the workflow
    # can declare the environment but cannot create its protection rules.
    "github_environment": "production",
    # False: an IAM OIDC provider is account-global and this account is shared
    # with staging, which creates it. `prod-deploy` imports it by its ARN, so
    # `staging-deploy` must be deployed first. Split the accounts and this
    # becomes True.
    "create_github_oidc_provider": False,
}
