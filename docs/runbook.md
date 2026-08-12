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

Four stacks per environment, deploy order following their dependencies:
`<env>-network` → `<env>-backend` → `<env>-frontend` → `<env>-pipeline`.

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

The frontend distribution gets a certificate; **the ALB does not**. Its listener is
plain **HTTP on port 80**, and the `AwsSolutions-EC23` suppression in
`backend_stack.py` says so in as many words rather than pretending otherwise. An HTTPS
listener needs a certificate, which needs the domain from step 2. When that lands, pass
`certificate` and `redirect_http_to_https=True` to
`ApplicationLoadBalancedFargateService` and narrow the suppression.

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
| `/api/*` CloudFront behavior to the ALB | Not defined; the distribution has only the default and `/assets/*` behaviors, both to S3 |
| Secrets in Secrets Manager, injected into the task | No secret and no task environment/secrets at all |
| ALB accepts 443 only | Listener is HTTP:80; no ACM certificate |
| ECS rolling deploy at `minimumHealthyPercent: 100` | Not configured; synth warns that the 50% default applies |
| CloudWatch alarms (5xx > 1%, CPU > 80%, unhealthy hosts) + SNS notification | No alarms exist. The only SNS topic is the pipeline's manual-approval topic |
| X-Ray tracing on ALB and ECS | Not enabled |
| VPC flow logs | Not enabled; suppressed in `network_stack.py` with a written reason |
| ALB / CloudFront / S3 access logs | Not enabled; each is a suppression with a written reason |

Auto-scaling (70% CPU target, min/max from `infra/config/`), the 30-day log retention,
ECR lifecycle (20 images), container insights, the S3 bucket's block-public-access +
OAC + `enforce_ssl`, and the App-level `Environment`/`Service`/`Owner` tagging **are**
implemented.
