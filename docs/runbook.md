# Runbook

Operating the AWS deployment: what exists, what does not, and the steps that have to be
done by hand.

> ## Read this first: what has actually been run
>
> **Staging has been deployed, torn down and redeployed from `scripts/deploy-to-aws.sh`**,
> against a real account, on a real domain — <https://qbiq.yossidemo.click>. The commands
> in the "Deploying" sections below have been executed rather than merely written.
>
> **Production has not.** No `prod-*` stack has ever existed, so every prod-specific
> instruction here is derived from the stack definitions rather than from having run it.
>
> **`.github/workflows/deploy.yml` has never completed a deploy.** Its gate fails on the
> first prerequisite — the `AWS_ACCOUNT_ID` repository variable is unset — and a push to
> `main` resolves its target to `production`, which does not exist. Standing an
> environment up is the script's job either way; see the table below.
>
> Sections describing operations that have not been exercised on a live system — secrets
> rotation in particular — are marked as such where they appear.

---

## What synthesizes today

```bash
python3 -m venv .venv
.venv/bin/pip install -r infra/requirements.txt
source .venv/bin/activate

cdk synth -c env=staging     # or -c env=prod
cdk list -c env=staging      # staging-network, staging-data, staging-ecr,
                             # staging-backend, staging-frontend, staging-deploy
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

Six stacks per environment. The deploy order follows their dependencies, with one step
that is not a stack at all:

`<env>-ecr` → **push an image** → `<env>-network` → `<env>-data` → `<env>-backend` →
`<env>-frontend` → `<env>-deploy`

That order is not a preference.

- `<env>-ecr` is first, and alone, **because of an image push that has to happen between
  it and `<env>-backend`.** `backend_stack.py` renders both of its task definitions
  against `<repo>:latest`; while the repository was created by that same stack, the first
  deploy created an empty registry and then waited for an ECS service whose tasks had
  nothing to pull. The service never stabilised and CloudFormation rolled the stack back
  after its timeout. Registry, image, then everything that consumes the image — see
  `infra/stacks/ecr_stack.py`.
- `<env>-frontend` reads the backend's load balancer DNS name for the CloudFront `/api/*`
  behavior, so it cannot be deployed before `<env>-backend` exists.

Every reference in the app runs one way — `backend → ecr`, `deploy → ecr`, and
network → data → backend → frontend with the deploy stack last — because a reference
pointing back the other way is a `DependencyCycle` that fails at synth. The ECR stack
imports nothing from any other stack, which is what lets it be deployed into an empty
account on its own.

There is one ordering constraint *between* environments as well: `staging-deploy` creates
the account-global GitHub OIDC provider and `prod-deploy` imports it, so staging's deploy
stack has to exist first. See "The deploy path" below.

---

## Before any `cdk deploy` can work

Five things, all of which currently block a real deploy.

### 1. The AWS account and the context lookups

`infra/config/staging.py` and `infra/config/prod.py` both set `account` to
`963352896991`, and **staging and production deliberately share it** — a simplification,
not a recommendation: a misconfigured staging deploy can reach production resources.
Split the accounts before this carries anything of value.

Context lookups used to be **seeded by hand in `cdk.json`** — a fake hosted-zone id and a
two-entry AZ list — because no credentials on the machine this was set up from reached
the account. Both seeds are gone. Lookups now resolve live and cache in
**`cdk.context.json`**, which is committed so CI synthesizes the same values a developer
does:

```jsonc
"availability-zones:account=963352896991:region=us-east-1": ["us-east-1a", ... ],
"hosted-zone:account=963352896991:domainName=yossidemo.click:region=us-east-1": {
  "Id": "/hostedzone/Z03443351PW97OGJ1VSIF",
  "Name": "yossidemo.click."
}
```

Never hand-write an entry in either file. A forged lookup synthesizes cleanly and fails
at deploy, which is the worst of both. To re-resolve one, delete its key and re-synth
from a session that can assume the CDK lookup role in the target account.

### 2. A real domain

**Staging has one.** `domain_name` is `yossidemo.click`, `frontend_domain` is
`qbiq.yossidemo.click`, and `custom_domain_enabled` is `True`, so `frontend_stack.py`
resolves the zone, issues a DNS-validated ACM certificate, adds the name to the
distribution and creates the A-alias record. **Do not create that alias record by hand** —
the stack owns it, and a pre-existing record collides with what CloudFormation creates.

**Production does not.** `prod.py` still carries `example.com` with the flag off, and
with it off the distribution serves on its generated `*.cloudfront.net` name and creates
no lookup, certificate or alias. That costs one suppressed cdk-nag finding —
`AwsSolutions-CFR4`, because the default CloudFront certificate pins viewer TLS to TLSv1
and cannot be given a stronger security policy.

Turning it on for an environment that does not have it:

1. **Register or delegate a real domain** and create its public hosted zone in Route 53.
   Neither is done by this CDK app; delegation means updating the NS records at the
   registrar, which is outside AWS entirely.
2. Set `domain_name` to the zone apex and `frontend_domain` to the host the SPA serves
   on, and set `custom_domain_enabled` to `True`.
3. Re-synth from a session that can assume the CDK lookup role, so the real zone id is
   resolved and cached into `cdk.context.json`.
4. `cdk deploy <env>-frontend`. **The certificate stack will sit in `CREATE_IN_PROGRESS`
   until DNS validation completes.** CDK writes the validation CNAME into the hosted zone
   for you, so this resolves itself if the zone really is delegated — and hangs for hours
   if it is not. That wait is the usual sign that step 1 was not actually finished.

The certificate is requested in this stack, which is in `us-east-1` in both configs;
CloudFront only reads viewer certificates from that region. `frontend_stack.py` raises at
synth if `custom_domain_enabled` is set in any other region rather than letting the
deploy discover it.

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

### 4. Three settings on the GitHub side

The CodeStar connection is gone — deploys run from GitHub Actions over OIDC
([ADR-004](adr/ADR-004-github-actions-over-codepipeline.md)), so there is no console
handshake to complete. What replaced it is three things in **GitHub** repository
settings, none of which the workflow can create for itself:

1. **The `production` environment** (Settings → Environments → New environment →
   `production`). Its name is not cosmetic: it appears in the OIDC subject claim the
   deploy role trusts, `repo:yosefsha/qbiq_h:environment:production`, and it must match
   `github_environment` in `infra/config/prod.py`. A mismatch fails the assume with
   `Not authorized to perform sts:AssumeRoleWithWebIdentity`, which says nothing about
   which claim was wrong.
2. **Required reviewers on that environment.** This is the production gate.
   `deploy.yml` declares `environment:`, which is what makes a job wait — but the
   protection rule itself is a repository setting, so **until someone adds a reviewer,
   production deploys unattended.** This is strictly weaker as a default than the
   CodePipeline manual-approval action it replaces, and it is the one property this
   change moved from enforced to configured.
3. **A deployment-branch policy on that environment**, limited to `main`. This is the
   only thing that binds the deploy to a branch. The trust policy cannot: one OIDC token
   carries one `sub`, and a job that declares an environment stops presenting the ref, so
   IAM can check *which environment* but not *which branch*. Without this rule, a
   `workflow_dispatch` from any branch that names the `production` environment can assume
   the role. (`deploy.yml` also guards on `github.ref == 'refs/heads/main'`, but that
   guard lives in a file a branch can edit.)

Repeat 1 and 3 for a `staging` environment if you intend to use the `workflow_dispatch`
staging target; it needs no reviewer.

Plus one repository **variable** (Settings → Secrets and variables → Actions →
Variables): `AWS_ACCOUNT_ID`, the account the stacks were deployed into. The workflow
builds the role ARN from it, because it has no credentials with which to look anything up
before it has assumed the role. `AWS_REGION` and `SERVICE_NAME` are optional and default
to `us-east-1` and `myapp`, matching `infra/config/`. There is deliberately **no AWS
secret** — nothing long-lived is stored in GitHub.

### 5. ECR must hold an image before `<env>-backend` is deployed

`backend_stack.py` renders both the service and the migration task definitions against
`<repo>:latest`. On a first deploy that tag does not exist, tasks cannot pull, the
service never stabilises, and the stack rolls back after CloudFormation's timeout.

This is why the repository lives in its own stack. `scripts/deploy-to-aws.sh` handles it
(steps 3 and 4) and you do not have to think about it. By hand it is:

```bash
cdk deploy staging-ecr -c env=staging --require-approval never
ECR_URI=$(aws cloudformation describe-stacks --stack-name staging-ecr \
  --query 'Stacks[0].Outputs[?OutputKey==`RepositoryUri`].OutputValue' --output text)

aws ecr get-login-password | docker login --username AWS --password-stdin "$ECR_URI"
docker build --platform linux/amd64 -t "$ECR_URI:latest" backend
docker push "$ECR_URI:latest"
```

**`--platform linux/amd64` is not optional on an Apple Silicon machine.** Fargate here
is x86_64. Without the flag Docker builds a native arm64 image that runs fine on the
laptop, pushes without complaint, and then dies in ECS with `exec format error` — visible
only in the task's CloudWatch stream, after ECS has already replaced the task, and
indistinguishable at a glance from a health-check failure.

The deploy workflow cannot do the bootstrap for you: it assumes a role that `<env>-deploy`
creates, and that stack is deployed after the backend stack. The first image is pushed
from a laptop, once per environment.

Also note `cdk bootstrap` must have been run for the account/region pair; the assets
these stacks synthesize need the CDK bootstrap bucket and roles.
`scripts/deploy-to-aws.sh` checks for the `CDKToolkit` stack and bootstraps only if it is
absent.

---

## What staging costs, and the three things that were traded for it

Staging is a demo environment, and it is shaped for cost rather than for resilience.
Three choices, each with a real consequence, so none of them is later "fixed" by someone
who only sees the downside:

| Choice | Saves | Consequence |
|---|---|---|
| **No NAT Gateway** (`nat_gateways=0`) | ~$32.85/mo | ECS tasks must run in **public subnets with public IPs** to reach ECR, Secrets Manager and CloudWatch Logs. Automatic rotation of the RDS secret is gone (see "Rotation is manual" below). |
| **One Fargate task** in staging (was two) | ~$9/mo | No AZ redundancy — the single task is in one AZ, and losing that AZ takes staging down until ECS reschedules. Rolling deploys still work. |
| Public IPv4 on that task | **costs** ~$3.65/mo | AWS bills $0.005/hr per in-use public IPv4 address. This is the part of the NAT saving that is given back. |

Net: **roughly $38/month less** for staging, before NAT data-processing charges (which
were $0.045/GB on top of the hourly rate and are now zero). Production keeps two tasks and
is otherwise unchanged, but it shares the network stack, so it too has no NAT Gateway and
its tasks are also in public subnets.

**What was rejected, and why.** Interface VPC endpoints for ECR (api and dkr), Secrets
Manager and CloudWatch Logs would let the tasks stay in private subnets. At ~$7.20/month
each, four of them is ~$29/month against the NAT's ~$32 — the same bill with more moving
parts, so this is not a saving. If the tasks must be private, restore the NAT Gateway
rather than building an endpoint mesh.

**A public IP is not public access.** The task security group admits inbound traffic from
the ALB security group on port 8000 and from nothing else, so the ALB remains the only
ingress path. The public IP exists so the task can make outbound calls. RDS and
ElastiCache did not move: they are in `PRIVATE_ISOLATED` subnets with no route to an
internet gateway at all, which is strictly stronger than the `PRIVATE_WITH_EGRESS`
subnets they were in before.

**Turning any of it back on:**

```python
# infra/stacks/network_stack.py
nat_gateways=1,
subnet_configuration=[..., ec2.SubnetConfiguration(
    name="Private", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=24)],

# infra/stacks/backend_stack.py — drop task_subnets and assign_public_ip
# infra/stacks/deploy_stack.py — task_subnets back to PRIVATE_WITH_EGRESS,
#                                DeployAssignPublicIp back to "DISABLED"
# infra/config/staging.py      — backend_desired_count / backend_min_tasks back to 2
```

Nothing reads `DeployAssignPublicIp` as a literal — both `deploy.yml` and
`scripts/deploy-to-aws.sh` take it from the stack output — so flipping it is one edit.

---

## Standing an environment up: `scripts/deploy-to-aws.sh`

There are three different jobs here, and they are not the same tool.

| Job | Tool | Runs |
|---|---|---|
| Create or rebuild an environment from nothing | `scripts/deploy-to-aws.sh` | By hand, from a laptop with real AWS credentials |
| Ship a merged commit to an environment that already exists | `.github/workflows/deploy.yml` | Automatically, on merge to `main`, over OIDC |
| Ship a **frontend-only** change to an environment that already exists | `scripts/deploy-frontend.sh` | By hand, same credentials as the first |

The workflow cannot do the first job: it has no permission to create infrastructure
(deliberately — see the docstring on `deploy_stack.py`), and it cannot push the first
image because it needs a role that does not exist until the stacks do. The script cannot
do the second: it wants credentials on a human's machine.

`scripts/deploy-frontend.sh` is the first script's steps 7 and 8 on their own — build the
SPA, sync it to the bucket, invalidate CloudFront, wait for the invalidation — for the
common case where nothing under `backend/` or `infra/` changed and the other seven steps
would be expensive no-ops. **Its narrowness is the thing to remember about it:** it never
builds an image, registers a task definition, migrates, seeds, or touches the ECS
service, so a backend change deployed with it succeeds and changes nothing. It also
cannot create infrastructure — the bucket and distribution come from the `<env>-deploy`
stack's outputs, and it says so rather than uploading into nothing if that stack is
absent.

```bash
./scripts/deploy-frontend.sh staging      # or prod; staging is the default
```

```bash
./scripts/deploy-to-aws.sh staging      # or prod; staging is the default
```

**It has been run against staging, repeatedly**, including a full teardown and rebuild —
which is what the staging removal policies are for: the RDS instance, the ElastiCache
group, the ECR repository and the SPA bucket all go with the stack, so a redeploy starts
clean instead of colliding with a retained resource. It has **never** been run against
prod, where every one of those is retained instead, so the first prod run is a first run.

Nine steps, and each one is a thing that would otherwise be a line in this runbook:

1. **Preflight.** Refuses an environment that is not `staging` or `prod`; fails if
   `aws sts get-caller-identity` does not work or returns an account other than the one
   in `infra/config/<env>.py`; fails if Docker is not running; fails if `.venv` is
   missing or has no `aws_cdk` in it. Prints the account, region, identity and version
   tag before touching anything. (`cdk.json` runs a bare `python3`, so the venv has to be
   on `PATH` or synthesis dies with `ModuleNotFoundError: No module named 'aws_cdk'`.)
2. **Bootstrap**, only if the `CDKToolkit` stack is absent.
3. **`cdk deploy <env>-ecr`**, then read `RepositoryUri` from its outputs.
4. **Build and push the image**, `--platform linux/amd64`, tagged twice: a traceable
   `<env>-<git-sha>-<timestamp>` and the moving `latest` that the CDK task definitions
   reference.
5. **`cdk deploy`** for `<env>-network`, `<env>-data`, `<env>-backend`, `<env>-frontend`
   and `<env>-deploy`, with `--require-approval never`. Expect 15-25 minutes; the banner
   says so, because a silent RDS create looks exactly like a hang.
6. **Migrate, then seed**, each as a one-off Fargate task on the `<service>-<env>-migrate`
   task definition, in the same subnets and the same security group the service's tasks
   use — that group is the only source the RDS ingress rule admits. The subnets are public
   and the task takes a public IP, read from `DeployAssignPublicIp` rather than hardcoded;
   without it the task cannot pull from ECR at all. Both commands are idempotent.
7. **Build and upload the SPA**: `npm ci && npm run build`, `aws s3 sync dist/ --delete`,
   then a CloudFront invalidation on `/*` that it waits for.
8. **Force a new ECS deployment** so the service picks up the pushed `latest`, and wait
   for the service to stabilise.
9. **Print** the CloudFront URL to open, the ALB DNS, the version tag and the git SHA.

**On the migration exit code.** `aws ecs run-task` returning successfully means the task
was *accepted* — not that it succeeded, and not even that it started. The script waits
for the task to stop (`aws ecs wait tasks-stopped`), reads the `migrate` container's exit
code with `describe-tasks`, and fails the whole script on any non-zero value. It also
fails when there is **no** exit code at all, which is the `CannotPullContainerError` case
(wrong architecture, or a tag that is not in the registry): a missing exit code is a task
that never ran, not a task that passed. The ECS service is only updated after both the
migration and the seed have exited `0`.

**Re-running it is safe.** Every `describe-stacks` read is guarded so an absent stack is
an empty string rather than an error, `cdk deploy` is a no-op when nothing changed, and
`alembic upgrade head` and `python -m app.seed` are both idempotent. A second run is an
update.

### Tearing one down: `scripts/destroy-aws.sh`

```bash
./scripts/destroy-aws.sh staging
```

`cdk destroy` in reverse order (`deploy`, `frontend`, `backend`, `data`, `network`,
`ecr`), skipping stacks that do not exist, behind a typed confirmation (`destroy staging`).

**It does not delete your data, and what survives keeps billing you.** In production the
RDS instance is `RETAIN`, so it stays and costs the full hourly instance price exactly as
if you had not run the script — and deletion protection is on, so even a manual delete is
refused until that is turned off. In staging it is `SNAPSHOT`, so the instance goes but a
final snapshot is retained and billed per GB-month for as long as it exists. The ECR
repository and the SPA bucket are also `RETAIN`. Removing any of them is a separate,
deliberate act.

---

## The deploy path

Two workflows, and the split between them is the point
([ADR-004](adr/ADR-004-github-actions-over-codepipeline.md)).

**`.github/workflows/ci.yml` is the gate.** ruff, pytest against real Postgres and Redis,
eslint, `vue-tsc`, vitest, and a build of both images, on every pull request and every
push to `main`. It is the only place the suite runs.

**`.github/workflows/deploy.yml` deploys.** On push to `main`, or on `workflow_dispatch`
with a `target` of `production` (default) or `staging`. Three jobs:

- **`gate`** — refuses anything that is not on `main`, resolves the target to a CDK stack
  prefix and a role ARN, then polls the GitHub API until `ci.yml` has concluded
  `success` **for this exact commit**, failing on any other conclusion and timing out
  after 45 minutes. The suite is deliberately not re-run here.
- **`backend`** — assumes the deploy role, reads the `<env>-deploy` stack's outputs,
  builds the image and pushes it as `:<commit-sha>` (and `:latest`, only as the bootstrap
  tag the CDK task definitions reference). Then, in order:
  1. register a **migration** task-definition revision pinned to `:<commit-sha>`, run it
     as a one-off Fargate task in the private subnets with the task security group,
     command `alembic upgrade head`;
  2. wait for that task to stop and **fail the job on a non-zero container exit code** —
     `run-task` returning successfully only means the task started;
  3. register a **service** task-definition revision pinned to the same tag and update
     the ECS service to it, waiting for stability.
- **`frontend`** — `npm ci`, `npm run lint`, `npm run build`, `aws s3 sync dist/ --delete`,
  then a CloudFront invalidation of `/*` which it waits on.

`backend` and `frontend` are independent: neither `needs` the other, so a failing SPA
build does not hold back an API fix.

**The migration is why the runner never needs to be in the VPC.** RDS is in private
subnets and admits only the ECS task security group, and a GitHub-hosted runner is a
machine on the public internet. So `alembic upgrade head` runs *inside* the VPC as an ECS
task, from the same image being deployed — the AWS equivalent of `docker-compose.yml`'s
`migrate` service. It has its own single-container task definition
(`myapp-<env>-migrate`) rather than a command override on the service's, because the
service's definition also carries the X-Ray sidecar and its shutdown exit code would fail
an honest exit-code check on every successful migration.

Container names are defined once in `backend_stack.py` (`CONTAINER_NAME = "backend"`,
`MIGRATION_CONTAINER_NAME = "migrate"`) and published as stack outputs, so the workflow
never hardcodes them. If a name ever disagreed, the render step would match no container
and the deploy would *succeed* while shipping the previous image — worth knowing about,
and the reason they are outputs rather than literals.

### Rolling back

Every deploy registers a task-definition revision pinned to an immutable
`:<commit-sha>` image, so a rollback is a redeploy of a known revision rather than a race
with a floating tag:

```bash
aws ecs list-task-definitions --family-prefix <family> --sort DESC --max-items 5
aws ecs update-service --cluster <cluster> --service <service> \
  --task-definition <family>:<revision>
aws ecs wait services-stable --cluster <cluster> --services <service>
```

**Migrations do not roll back with it.** `alembic upgrade head` has already run by the
time the service is updated, so rolling the service back leaves the schema ahead of the
code. That is safe for additive migrations and is not safe for a destructive one — a
destructive migration has to be split into a backwards-compatible pair of releases, or
reversed by hand with `alembic downgrade`.

None of these commands have been run against a live service.

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

### Rotation is manual, and that is a consequence of removing the NAT Gateway

**Neither secret rotates automatically.** The database secret used to: `data_stack.py`
called `add_rotation_single_user` with a 30-day schedule. That was removed when the NAT
Gateway was, because Secrets Manager's managed rotation runs as a Lambda inside the VPC
and has to call the Secrets Manager API to finish the rotation. With no NAT there is no
route to that API, and a Lambda in a VPC never gets a public IP of its own — so the
public-subnet arrangement the ECS tasks use has no equivalent here. Left configured it
would not have failed at deploy; it would have failed every 30 days, quietly, marking the
secret rotation-failed where nobody was looking.

Restoring it costs **one Secrets Manager interface VPC endpoint (~$7.20/month)** and one
argument: pass `endpoint=` to `add_rotation_single_user`. That trade is recorded in the
`AwsSolutions-SMG4` suppression on the secret, so it stays a decision rather than an
omission.

The Redis AUTH token never rotated and is the harder of the two: AWS publishes no managed
rotation function for one, because changing it is a two-phase `ModifyReplicationGroup`
against the cluster rather than a write to a datastore. That needs a custom Lambda.

**Rotating by hand (not yet executable — nothing has been deployed):** rotating a value in
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
