# `account` is the real AWS account, shared with production for now. See the
# note in prod.py: this is a simplification to unblock a single-account setup,
# not a recommendation.
#
# A real domain, at last. `yossidemo.click` is a registered domain with a public
# hosted zone in this account (Z03443351PW97OGJ1VSIF), which replaces the
# `example.com` placeholder this file carried while no zone existed.
#
# With `custom_domain_enabled` True, frontend_stack.py resolves that zone,
# issues an ACM certificate for `frontend_domain` validated by DNS records it
# writes into the zone itself, adds the name to the distribution, and creates
# the A-alias record pointing at CloudFront. None of that is a manual step —
# in particular, do not hand-create the alias record, because the stack owns it.
#
# The certificate is a plain `acm.Certificate` in this stack, which is only
# valid for CloudFront because `region` is us-east-1; frontend_stack.py raises
# at synth if that ever stops being true.
STAGING_CONFIG = {
    "environment": "staging",
    "account": "963352896991",
    "region": "us-east-1",
    "service_name": "myapp",
    "owner": "platform-team",
    "domain_name": "yossidemo.click",
    "frontend_domain": "qbiq.yossidemo.click",
    "custom_domain_enabled": True,
    # ONE task in staging, not two. This reverses what INF-05 decided here, and
    # the reversal is deliberate, so the old reasoning is restated rather than
    # deleted: two tasks kept the service off a single AZ and gave a rolling
    # deploy at minimumHealthyPercent 100 somewhere to shift traffic to, which is
    # a property worth rehearsing before production relies on it.
    #
    # Staging is a demo environment and cost won. One 0.25 vCPU / 0.5 GB Fargate
    # task is ~$9/month, and it is not worth that to rehearse a deployment
    # property in an environment nobody is depending on.
    #
    # **A rolling deploy still works at one task.** minimumHealthyPercent 100 with
    # maximumPercent 200 lets ECS start the replacement *before* stopping the
    # original — 1 task, ceiling of 2 — so there is no gap in availability. What
    # is actually given up is AZ redundancy: a single task lives in one AZ, and
    # losing that AZ takes staging down until ECS reschedules. Production keeps
    # two (infra/config/prod.py) and is not touched by this.
    #
    # max is 2, not 10. Staging is a short-lived demo and nothing load-tests it;
    # a ceiling of 10 only decides how expensive a runaway scaling event is
    # allowed to get. Raise it again the day something actually load-tests here.
    "backend_desired_count": 1,
    "backend_min_tasks": 1,
    "backend_max_tasks": 2,
    # Protocol the ALB listener speaks — one key, read by backend_stack.py to
    # build the listener and by frontend_stack.py for CloudFront's
    # OriginProtocolPolicy on the `/api/*` behaviour. They have to agree or the
    # edge answers 502 and nothing in the application log says why, which is
    # why this is a single setting rather than one on each side.
    # "HTTPS" switches the listener to 443 (plus an HTTP:80 listener that only
    # redirects) and requires `alb_certificate_arn` below.
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
    # Zero, not one. Automated backups of a demo database that is recreated from
    # migrations on every deploy protect nothing, and a retention of 0 also skips
    # the backup window, so the instance reaches `available` sooner. Production
    # keeps 14 (infra/config/prod.py).
    "db_backup_retention_days": 0,
    "db_multi_az": False,
    "db_deletion_protection": False,
    "cache_node_type": "cache.t4g.micro",
    # Zero replicas — a single node. This reverses the earlier choice here, so
    # the old reasoning is restated rather than deleted: one replica gave
    # automatic failover somewhere to fail over to, which is the property
    # ADR-003 chose Redis for, and staging could therefore rehearse it.
    #
    # Staging is a short demo and cost won, exactly as it did for the task count
    # above: the replica is a second cache.t4g.micro node running continuously to
    # exercise a property nothing here depends on. data_stack.py derives
    # `automatic_failover_enabled` and `multi_az_enabled` from this number, so
    # setting it back to 1 restores failover with no other edit. Production is
    # untouched and keeps its replica.
    "cache_replicas": 0,
    # No snapshots. Carts and sessions in a demo are disposable, and the daily
    # snapshot is billed storage plus a slower teardown.
    "cache_snapshot_retention_days": 0,
    # Deploys come from GitHub Actions over OIDC, not from CodePipeline — see
    # ADR-004. These three keys are the whole of what the deploy role trusts.
    "github_owner": "yosefsha",
    "github_repo": "qbiq_h",
    # Deployment branch. The trust policy cannot enforce it (one OIDC token
    # carries one `sub`, and a job that declares an environment stops presenting
    # the ref), so this value is what the GitHub environment's deployment-branch
    # policy must be set to by hand — see docs/runbook.md.
    "github_branch": "main",
    # The GitHub *environment* whose name appears in the OIDC subject claim:
    # `repo:yosefsha/qbiq_h:environment:staging`. It must match the `environment:`
    # key on the staging jobs in .github/workflows/deploy.yml, or the role refuses
    # the assume with an unhelpful "Not authorized to perform sts:AssumeRoleWithWebIdentity".
    "github_environment": "staging",
    # An IAM OIDC provider is account-global and staging shares an account with
    # production, so exactly one environment may create it — and in this account
    # the provider already exists, created outside CDK. Both environments
    # therefore import it by its (fully determined) ARN and neither creates it.
    #
    # Set this to True only for an account that has no
    # `token.actions.githubusercontent.com` provider yet; deploying it against
    # one that does fails with `EntityAlreadyExists`, because an IAM OIDC
    # provider is account-global and unique per URL. Check before flipping it:
    #
    #   aws iam list-open-id-connect-providers
    "create_github_oidc_provider": False,
}
