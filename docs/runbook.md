# Runbook

Operating the AWS deployment: what exists, what does not, and the steps that have to be
done by hand.

> ## Read this first: nothing has ever been deployed
>
> `cdk synth` succeeds for both environments — that is the whole of what has been
> verified. No `cdk deploy` has been run, no AWS resource has been created, and no
> pipeline has executed. Every command in the "Deploying" section below **will fail
> today** until the prerequisites listed there are satisfied. Sections that describe
> operating a live system (secrets rotation, reading logs) are written from the stack
> definitions and are marked as unexecuted.

---

## What synthesizes today

```bash
python3 -m venv .venv
.venv/bin/pip install -r infra/requirements.txt
source .venv/bin/activate

cdk synth -c env=staging     # or -c env=prod
cdk list -c env=staging      # staging-network, staging-backend, staging-frontend, staging-pipeline
```

`cdk.json` at the repo root points the CLI at `infra/app.py`, so run these from the repo
root, not from `infra/`. The CDK **CLI** is a Node package and is not installed by
`infra/requirements.txt`:

```bash
npm install -g aws-cdk@2     # or run ad hoc: npx aws-cdk@2 synth -c env=staging
```

`-c env=` defaults to `staging` when omitted. `cdk-nag`'s `AwsSolutionsChecks` runs as an
Aspect on every synth, so a new resource that trips a rule fails synthesis rather than
review; the existing suppressions each carry a written reason in the stack that owns
them. Synth currently emits warnings (duplicate subnets in the ALB property, no ECS
circuit breaker, `minHealthyPercent` defaulting to 50%) but no errors.

Five stacks per environment, deploy order following their dependencies:
`<env>-network` → `<env>-data` → `<env>-backend` → `<env>-frontend` → `<env>-pipeline`.

That order is not a preference. `<env>-frontend` reads the backend's load balancer DNS
name for the CloudFront `/api/*` behavior, so it cannot be deployed before
`<env>-backend` exists. Every reference in the app runs one way — network → data →
backend → frontend, with the pipeline last — because a reference pointing back the other
way is a `DependencyCycle` that fails at synth.

---

## Before any `cdk deploy` can work

Five things, all of which currently block a real deploy.

### 1. The AWS account and the seeded context lookups

`infra/config/staging.py` and `infra/config/prod.py` both set `account` to
`963352896991`, and **staging and production deliberately share it** — a simplification,
not a recommendation: a misconfigured staging deploy can reach production resources.
Split the accounts before this carries anything of value.

No credentials on the machine this was set up from can reach that account, so CDK's
context lookups are **seeded by hand in `cdk.json`** rather than resolved live:

```jsonc
"hosted-zone:account=963352896991:domainName=example.com:region=us-east-1": {
  "Id": "/hostedzone/ZZZZZZZZZZZZZZZZZZZZ",   // fake — this zone does not exist
  "Name": "example.com."
},
"availability-zones:account=963352896991:region=us-east-1": ["us-east-1a", "us-east-1b"]
```

The seeded AZs are what makes offline synthesis work, and they are a placeholder: AZ
names map to different physical zones per account. Delete that key and re-synth from a
session that can assume the CDK lookup role in the target account.

The seeded **hosted zone is not read at all today** — `custom_domain_enabled` is `False`
in both configs, so `frontend_stack.py` never calls `HostedZone.from_lookup`. The seed is
kept only so that flipping the flag still synthesizes offline; the id
`ZZZZZZZZZZZZZZZZZZZZ` is fake and must be deleted before a deploy with a real domain.

### 2. A real domain (optional — the distribution deploys without one)

`domain_name` is `example.com` and `frontend_domain` is `staging.example.com` /
`app.example.com` — placeholders, and `custom_domain_enabled` is `False`. With the flag
off, `frontend_stack.py` creates **no hosted-zone lookup, no ACM certificate and no
Route 53 alias**, and the distribution serves on its generated `*.cloudfront.net` name.
That is deliberate: a DNS-validated certificate against a zone that does not exist
synthesizes cleanly and can never deploy, so the certificate is absent rather than
fabricated. The cost of the flag being off is one suppressed cdk-nag finding —
`AwsSolutions-CFR4`, because the default CloudFront certificate pins viewer TLS to
TLSv1 and cannot be given a stronger security policy.

Turning it on, and what stays manual:

1. **Register or delegate a real domain** and create its public hosted zone in Route 53.
   Neither is done by this CDK app; delegation means updating the NS records at the
   registrar, which is outside AWS entirely.
2. Set `domain_name` to the zone apex and `frontend_domain` to the host the SPA serves
   on, in `infra/config/staging.py` and `infra/config/prod.py`, and set
   `custom_domain_enabled` to `True`.
3. Delete the seeded `hosted-zone:` key from `cdk.json` and re-synth from a session that
   can assume the CDK lookup role, so the real zone id is resolved.
4. `cdk deploy <env>-frontend`. **The certificate stack will sit in `CREATE_IN_PROGRESS`
   until DNS validation completes.** CDK writes the validation CNAME into the hosted zone
   for you, so this resolves itself if the zone really is delegated — and hangs for hours
   if it is not. That wait is the usual sign that step 1 was not actually finished.

The certificate is requested in this stack, which is in `us-east-1` in both configs;
CloudFront only reads viewer certificates from that region. `frontend_stack.py` raises at
synth if `custom_domain_enabled` is set in any other region rather than letting the
deploy discover it.

### 3. An ACM certificate for the ALB

The frontend distribution can get a certificate; **the ALB has none**. Its listener is
plain **HTTP on port 80**, and the `AwsSolutions-EC23` suppression in
`backend_stack.py` says so in as many words rather than pretending otherwise. An HTTPS
listener needs a certificate, which needs the domain from step 2. When that lands, pass
`certificate` and `redirect_http_to_https=True` to
`ApplicationLoadBalancedFargateService` and narrow the suppression.

**Two things have to move together.** `alb_listener_protocol` in `infra/config/*.py` is
what CloudFront uses to reach the ALB on the `/api/*` behavior. It is `"HTTP"` today. If
the listener becomes HTTPS and this is not flipped with it — or the reverse — the edge
returns `502` and nothing in the application logs explains why, because the request never
reaches a container. Flipping it to `"HTTPS"` also removes the `AwsSolutions-CFR5`
suppression automatically: `frontend_stack.py` only adds that suppression on the HTTP
branch.

One subtlety for whoever does that work: the `/api/*` behavior forwards the viewer's
`Host` header (`ALL_VIEWER`), and CloudFront uses that name for SNI to the origin. The
ALB's certificate therefore has to cover the **public** host — `frontend_domain` — not
the `*.elb.amazonaws.com` name.

### 4. CodeStar Connections — a manual, console-only step

`codestar_connection_arn` is `REPLACE_WITH_CODESTAR_CONNECTION_ARN` in both configs.
This one **cannot be automated**: CDK can create a connection resource, but the GitHub
OAuth handshake that moves it from `PENDING` to `AVAILABLE` has to be completed by a
human in the AWS console (Developer Tools → Settings → Connections → *Update pending
connection*, then authorise the AWS Connector for GitHub app against `yosefsha/qbiq_h`).
Paste the resulting ARN into `infra/config/staging.py` and `prod.py` before deploying the
pipeline stack. A pipeline deployed against a `PENDING` connection deploys fine and then
fails at the Source stage.

### 5. ECR is empty on a brand-new environment

`backend_stack.py` renders the task definition against `<repo>:latest`. On a first
deploy that tag does not exist, tasks cannot pull, the service never stabilises, and the
stack rolls back. Break the cycle by pushing any image to the repository before
deploying the backend stack — the pipeline's backend build pushes both `latest` and the
commit-SHA tag, so running it once is enough, as is a manual `docker build` + `docker
push`.

Also note `cdk bootstrap` must have been run for the account/region pair; the assets
these stacks synthesize need the CDK bootstrap bucket and roles.

---

## The pipeline

`<env>-pipeline` is scoped to a single environment — it holds direct references to that
environment's ECS service, S3 bucket and CloudFront distribution, so one pipeline cannot
promote staging into production. Stages:

- **Source** — GitHub via CodeStar Connections, branch `main`.
- **Build** — two CodeBuild projects in parallel:
  - *backend*: `pip install -r requirements-dev.txt`, `pytest -q`, `docker build`, push
    both `:$CODEBUILD_RESOLVED_SOURCE_VERSION` and `:latest` to ECR, write
    `imagedefinitions.json`.
  - *frontend*: `npm ci`, `npm run lint`, `npm run build` (which runs `vue-tsc` first, so
    a type error fails the pipeline).
- **Approve** — a manual approval action, **production only**, notified via the
  `ApprovalTopic` SNS topic. Subscribe an email or PagerDuty endpoint to it, or the
  approval sits unnoticed.
- **Deploy-\<Env\>** — `EcsDeployAction` for the backend and `S3DeployAction` for the
  frontend, running independently at the same `run_order`, followed by a CloudBuild-run
  CloudFront invalidation of `/*` (CodePipeline has no native invalidation action).

The container name is `backend`, defined once as `CONTAINER_NAME` in `backend_stack.py`
and passed into the pipeline. If the two ever disagree, `EcsDeployAction` matches nothing
and the deploy *succeeds* while changing no image — a silent no-op worth knowing about.

---

## Secrets

**Nothing in `infra/` creates a Secrets Manager secret today, and the ECS task
definition injects no secrets or environment variables at all.** There is no
`DATABASE_URL` or `REDIS_URL` on the deployed task, so the container would fall back to
its `localhost` defaults from `app/settings.py`. `/health` would still return `200`,
because it touches neither store — so a green ALB health check would *not* mean the app
can serve a product. This is a direct consequence of the missing data stack (INF-04):
credentials are generated by the store that owns them, and there is no store yet.

When the data stack lands, secrets belong in Secrets Manager and are injected into the
task definition via `ecs.Secret.from_secrets_manager` — never baked into an image, never
committed to `infra/config/`.

**Rotation (not yet executable — no secret exists to rotate):** rotating a value in
Secrets Manager does not restart running tasks, because ECS resolves secrets at task
start. The rotation is therefore two steps — change the secret, then force a new
deployment so tasks pick it up:

```bash
aws secretsmanager put-secret-value --secret-id <arn> --secret-string '<new value>'
aws ecs update-service --cluster <cluster> --service <service> --force-new-deployment
```

Both commands are written from the AWS API contract, not from a run against this
account.

---

## Logs

`backend_stack.py` creates a CloudWatch log group with **30-day retention** and stream
prefix `backend`, wired to the task definition's `awslogs` driver. The group name is
CDK-generated (`<stack>-BackendLogs<hash>`), so find it before tailing it:

```bash
aws logs describe-log-groups --log-group-name-prefix staging-backend
aws logs tail <log-group-name> --follow --since 15m
```

The application logs structured JSON (`python-json-logger`), one object per line, with
`request_id` on every record and a matching `X-Request-Id` response header — so a user
reporting a failed request gives you the exact filter:

```bash
aws logs tail <log-group-name> --filter-pattern '{ $.request_id = "<id from the header>" }'
```

Every request produces a `request started` and a `request completed` line (with
`status_code`); an unhandled exception produces `request failed` with a traceback and a
500 response. The session token is deliberately never logged — it is a bearer
credential, and 30-day retention would keep it readable by anyone with log access.

These commands have not been run against a live log group, because no task has ever run.

---

## Documented elsewhere but not implemented

`CLAUDE.md` describes the production-grade target. Where the CDK does not yet match it,
the gap is here rather than hidden:

| Described | Reality |
|---|---|
| RDS Postgres + ElastiCache Redis | No data stack exists (`infra/stacks/data_stack.py` is absent) — INF-04 |
| Secrets in Secrets Manager, injected into the task | No secret and no task environment/secrets at all |
| ALB accepts 443 only | Listener is HTTP:80; no ACM certificate. CloudFront therefore reaches it over HTTP (`alb_listener_protocol`), suppressing `AwsSolutions-CFR5` |
| Custom domain via Route 53 + ACM certificate for the SPA | `custom_domain_enabled` is `False` in both configs — no real domain exists. The distribution serves on `*.cloudfront.net`, which suppresses `AwsSolutions-CFR4`. Set a real domain and flip the flag; see "A real domain" above |
| ECS rolling deploy at `minimumHealthyPercent: 100` | Not configured; synth warns that the 50% default applies |
| CloudWatch alarms (5xx > 1%, CPU > 80%, unhealthy hosts) + SNS notification | No alarms exist. The only SNS topic is the pipeline's manual-approval topic |
| X-Ray tracing on ALB and ECS | Not enabled |
| VPC flow logs | Not enabled; suppressed in `network_stack.py` with a written reason |
| ALB / CloudFront / S3 access logs | Not enabled; each is a suppression with a written reason |

Auto-scaling (70% CPU target, min/max from `infra/config/`), the 30-day log retention,
ECR lifecycle (20 images), container insights, the S3 bucket's block-public-access +
OAC + `enforce_ssl`, the CloudFront `/api/*` behavior to the ALB (INF-06), and the
App-level `Environment`/`Service`/`Owner` tagging **are** implemented.
