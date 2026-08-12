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
cdk list -c env=staging      # staging-network, staging-data, staging-backend, staging-frontend, staging-pipeline
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
them. Synth currently emits warnings (duplicate subnets in the ALB and subnet-group
properties, a stale RDS instance-class validator entry) but no errors.

Five stacks per environment, deploy order following their dependencies:
`<env>-network` → `<env>-data` → `<env>-backend` → `<env>-frontend` → `<env>-pipeline`.

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

That is what makes offline synthesis work and what makes a deploy fail: CloudFormation
would be handed a hosted zone id of `ZZZZZZZZZZZZZZZZZZZZ`. AZ names also map to
different physical zones per account, so the seeded AZs are a placeholder too. Delete
both seeded keys and re-synth from a session that can assume the CDK lookup role in the
target account.

### 2. A real domain

`domain_name` is `example.com` and `frontend_domain` is `staging.example.com` /
`app.example.com` — placeholders. `frontend_stack.py` looks the zone up and requests a
DNS-validated ACM certificate against it, so a real, delegated hosted zone has to exist
first (INF-06).

### 3. An ACM certificate for the ALB

**The ALB listens on plain HTTP:80 today.** `CLAUDE.md` says it should admit 443 only;
the synthesized template says otherwise, and the `AwsSolutions-EC23` suppression in
`backend_stack.py` states that rather than pretending. An HTTPS listener needs a
certificate, which needs the real domain from step 2, so this cannot be closed from
code alone.

What *is* in code is the switch. Two keys in `infra/config/<env>.py`:

```python
"alb_listener_protocol": "HTTPS",                       # default "HTTP"
"alb_certificate_arn": "arn:aws:acm:us-east-1:…:certificate/…",
```

With those set, `backend_stack.py` builds an **HTTPS:443 listener** on the certificate
with `ELBSecurityPolicy-TLS13-1-2-2021-06`, plus an HTTP:80 listener whose only action
is a `301` to HTTPS. Setting the protocol to `HTTPS` without a certificate ARN **fails
at synth** with a message naming the missing key — a half-configured environment cannot
quietly deploy plaintext.

Three things to know before flipping it:

- `alb_listener_protocol` is read by **both** `backend_stack.py` (to build the listener)
  and `frontend_stack.py` (for CloudFront's `OriginProtocolPolicy` on `/api/*`). One key,
  because a disagreement between the two is a 502 at the edge with nothing in the
  application log to explain it. Change it once and both follow.
- **The certificate must cover `frontend_domain`**, not the ALB's own
  `*.elb.amazonaws.com` name. CloudFront's `/api/*` behavior forwards the viewer's `Host`
  header and uses that value for SNI to this origin, so a certificate issued for the ALB
  hostname fails the handshake.
- Even on HTTPS the ALB is **not literally "443 only"**: port 80 stays open for the
  redirect listener. Drop `redirect_http` from `_listener_configuration` if that
  literal reading matters more than a redirect for anyone who types `http://`.

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

## Secrets and how the app is configured

The data stack (INF-04) generates the database password and the Redis AUTH token into
**Secrets Manager**, and the task definition injects them as `secrets` entries that ECS
resolves at task start. They appear in no image layer, no CloudFormation template and no
file in this repository. `aws ecs describe-task-definition` shows only the secret ARN.

The non-secret parts — `DB_HOST`, `DB_PORT`, `DB_NAME`, `REDIS_HOST`, `REDIS_PORT`,
`REDIS_TLS` — are plain environment variables, alongside the application's own settings
(`ALLOWED_ORIGINS`, `COOKIE_SECURE`, the two TTLs, `LOG_LEVEL`) from `infra/config/`.

**Those are the parts, not the URLs, and that used to be the whole problem.** Until
INF-05, `app/settings.py` read a single `DATABASE_URL` and a single `REDIS_URL` and
nothing set either, so a deployed container silently used its `localhost` defaults,
failed every query, and still answered `/health` with `200`. The URL cannot be assembled
at synth time — the password does not exist until CloudFormation generates it — so
`app/settings.py` now composes it at import:

- `DATABASE_URL` / `REDIS_URL`, when set, always win. Docker Compose and CI set them and
  are unaffected.
- Otherwise `DB_HOST` / `REDIS_HOST` trigger composition from the parts, with the
  credentials **percent-encoded** (a generated password containing `/`, `@`, `#` or `:`
  otherwise produces a URL that parses wrongly). `REDIS_TLS=true` selects `rediss://`,
  which ElastiCache requires with encryption in transit.
- `DB_HOST` set with any of `DB_NAME` / `DB_USERNAME` / `DB_PASSWORD` missing raises at
  import and the task dies loudly, rather than falling back to `localhost`.

**Rotation (not yet executable — nothing has been deployed):** rotating a value in
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

## Health checks: what a red target actually means

The ALB target group checks `GET /health` every 30s, and ECS replaces any task the
target group calls unhealthy. `backend/app/health.py` therefore **latches**: it probes
Postgres (`SELECT 1`) and Redis (`PING`) until both answer once, and from then on the
endpoint is a boolean read that touches nothing.

That is a deliberate asymmetry, and it is what the two failure modes need:

- **A task that never becomes healthy is misconfigured.** It cannot reach a store, so it
  never joins the target group, the deployment circuit breaker trips, and the release
  rolls back to the previous task set. Before INF-05 this was invisible: `/health`
  touched neither store, so a task with no `DATABASE_URL` at all reported `200` and
  served 500s to real traffic.
- **A task that was healthy and then sees a dependency blip stays healthy.** A blip says
  nothing about whether *that task* is configured correctly, and failing every task at
  once would have ECS replace the entire service over an outage it cannot fix. Requests
  that need the store fail on their own account while it lasts.

Diagnosing a task that will not go healthy:

```bash
aws logs tail <log-group-name> --filter-pattern '{ $.message = "health check*" }'
```

`health check dependency unavailable` carries `dependency` (`database` or `cache`) and
the traceback. The HTTP response deliberately says only `{"status": "unavailable"}` —
`/health` is reachable from the internet through the ALB, and which of two backing stores
an anonymous caller can see is not worth publishing.

Health check parameters, all in `backend_stack.py`: 30s interval, 5s timeout, 2 checks to
become healthy, 3 to become unhealthy, and a 60s grace period after task start so the
first check does not kill a task that is still importing the application.

---

## Alarms

Three CloudWatch alarms, all in `backend_stack.py`, all notifying the stack's own
`AlarmTopic`:

| Alarm | Fires when | First thing to look at |
|---|---|---|
| `Alb5xxRate` | ELB + target 5xx exceed **1% of requests** over 2×5min | `request failed` lines in the backend log group |
| `ServiceCpuHigh` | ECS service CPU ≥ **80%** over 3×5min | Whether autoscaling has hit `backend_max_tasks` |
| `UnhealthyTargets` | **any** unhealthy target for 3×1min | The health-check section above |

A rate, not a count, for the 5xx alarm: a fixed count fires on a quiet night at a rate
nobody notices at midday. `UnhealthyTargets` treats missing data as **breaching**,
because the metric is absent when there are no registered targets at all — the worst
state the service can be in, not a quiet one.

**Nobody is subscribed.** `alarm_email` is `None` in both `infra/config/` files, so the
topic exists, the alarms change state and the console shows them, but no message leaves
AWS. Set `alarm_email` to a real address (or subscribe a PagerDuty endpoint by hand) or
these are console decoration.

---

## Documented elsewhere but not implemented

`CLAUDE.md` describes the production-grade target. Where the CDK does not yet match it,
the gap is here rather than hidden:

| Described | Reality |
|---|---|
| `/api/*` CloudFront behavior to the ALB | Not defined; the distribution has only the default and `/assets/*` behaviors, both to S3 |
| ALB accepts 443 only | Listener is HTTP:80. The HTTPS:443 path is built and synthesizes, but is off for want of a certificate — see "An ACM certificate for the ALB" above. Even switched on, port 80 stays open as a 301 redirect |
| X-Ray tracing on ALB and ECS | Half. The daemon sidecar and its IAM grant are in the task definition, so segments have somewhere to go; **the application does not emit any**, so no trace appears until FastAPI is instrumented. An ALB cannot be traced on its own — it only stamps `X-Amzn-Trace-Id` |
| Alarm notifications actually reaching a human | The SNS topic and all three alarm actions exist, but `alarm_email` is `None` in both configs, so the topic has no subscriber. Set it, or subscribe by hand |
| The data stack's `CacheMemoryPressure` alarm | Still has no action. Its topic would have to come from this stack, and data must not reference backend (`DependencyCycle`). Move the topic to its own stack, or to the network stack, to wire it |
| VPC flow logs | Not enabled; suppressed in `network_stack.py` with a written reason |
| ALB / CloudFront / S3 access logs | Not enabled; each is a suppression with a written reason |

Implemented: RDS Postgres + ElastiCache Redis in private subnets with credentials in
Secrets Manager injected as task `secrets`; the rolling deployment at
`minimumHealthyPercent: 100` / `maximumPercent: 200` with a deployment circuit breaker
that rolls back; auto-scaling (70% CPU target, min/max from `infra/config/`); the three
CloudWatch alarms; 30-day log retention; ECR lifecycle (20 images); container insights;
the S3 bucket's block-public-access + OAC + `enforce_ssl`; and the App-level
`Environment`/`Service`/`Owner` tagging.
