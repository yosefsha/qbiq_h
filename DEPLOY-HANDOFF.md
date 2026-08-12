# Deploy handoff — resume here

Scratch file. Delete it once the first deploy is done.

Written 2026-08-12. **Nothing has been deployed yet.**

---

## Where things stand

- **All code is merged to `main`** — commit `270cfd2` (PR #60), from two commits:
  `8e3bc7a` (deploy script + ECR split) and `e7901c5` (no NAT Gateway, one staging task).
- **CI green on that commit**: backend ruff+pytest, frontend eslint/vue-tsc/vitest, docker
  image builds, Claude review — all four passed.
- **Nothing has ever been deployed.** No `cdk deploy`, no `cdk bootstrap`, no AWS resource.
  `scripts/deploy-to-aws.sh` has never executed. Everything below is a first run.
- **There is no code left to write.** The only thing blocking the run was the terminal's
  default AWS account.

## Which branch

**Deploy from `main`.** `deploy-run` and `feat/deploy-script` can both be deleted.

`deploy-run` is identical in content to `main` right now (verified with `git diff`
`e7901c5` vs `270cfd2` — no difference), because nothing else landed between the branch
point and the merge. But it is stale the moment anything else merges, and the script tags
the image with `git rev-parse --short HEAD`, so deploying from it would put a commit in the
ECR tag that is not on `main` — defeating the point of the tag.

## The one blocker, and it is not in the repo

```
the shell used on 2026-08-12 : 150758095463  (user/OptimaiDev)   <- wrong, stale default
infra/config/*.py            : 963352896991                       <- the target
```

`infra/config/staging.py` and `infra/config/prod.py` are **correct as they are. Do not edit
them.** Open a fresh shell (or `export AWS_PROFILE=<the 963352896991 profile>`) and confirm
before anything else:

```bash
aws sts get-caller-identity --query Account --output text   # must print 963352896991
```

The script's preflight checks this itself and refuses on a mismatch, so a wrong shell costs
seconds, not a half-built environment in the wrong account.

Note: `cdk.json` carries a hand-seeded `availability-zones:account=963352896991:...` key
(from INF-03, so `cdk synth` works offline). With real credentials for that account CDK
uses the seed rather than looking up. The values are `us-east-1a` / `us-east-1b`, which are
almost certainly fine — but if the VPC create fails on an AZ, delete that key from
`cdk.json` and re-run so CDK resolves the real list.

## Resume

```bash
cd /Users/yosefshachnovsky/dev/qbiq_h
git checkout main
git pull                                                     # should be at 270cfd2

aws sts get-caller-identity --query Account --output text     # 963352896991

./scripts/deploy-to-aws.sh staging
```

Run from the **repo root**: `cdk.json` lives there and points the CLI at `infra/app.py`.
From inside `infra/` you get `--app is required either in command-line, in cdk.json or in
~/.cdk.json`. The script `cd`s to the root itself, so this only bites manual `cdk` commands.

## What the script does, in order

Nine steps, roughly 20–30 minutes.

1. Preflight — account, Docker, venv. Creates nothing.
2. `cdk bootstrap`, only if the `CDKToolkit` stack is absent. **It will be absent.**
3. Deploy `staging-ecr`, read `RepositoryUri`.
4. `docker build --platform linux/amd64`, push `staging-<sha>-<timestamp>` and `latest`.
5. Deploy `staging-network`, `staging-data`, `staging-backend`, `staging-frontend`,
   `staging-deploy`. **15–25 minutes, mostly silent** — that is RDS and ElastiCache
   creating. It is not a hang.
6. `alembic upgrade head`, then `python -m app.seed`, each as a one-off Fargate task.
7. `npm ci && npm run build`, `s3 sync --delete`, CloudFront invalidation.
8. Force a new ECS deployment, wait for the service to stabilise.
9. Print the CloudFront URL to open.

Re-running is safe: every stack read is guarded, `cdk deploy` is a no-op when nothing
changed, and both the migration and the seed are idempotent.

## Where it is most likely to fail

**Step 5, `staging-data`.** Slowest by far. A failure here is usually an account quota
(RDS storage, ElastiCache nodes) rather than anything in the template.

**Step 6, the migration.** The interesting one — it exercises the part of the NAT-Gateway
removal never observed live. The task runs in a **public subnet with a public IP**, the
only way it reaches ECR without a NAT.

- **No exit code** = the container never ran. Almost always `CannotPullContainerError`: no
  route to ECR, or a wrong-architecture image. The script fails loudly here by design.
- **Non-zero exit** = the migration raised. The service is not updated.

Either way the ECS service is only updated after both the migration and the seed exit `0`.

**Step 8.** The deployment circuit breaker is on with rollback, so a release whose tasks
never pass `/health` gets reverted by ECS. The script waits for stability and fails if that
happens, rather than printing a URL for a version that quietly rolled back.

## What you are accepting by running this

- **Billable, and `destroy-aws.sh` will not fully undo it.** Staging RDS is `SNAPSHOT`, so
  teardown leaves a final snapshot billed per GB-month. The ECR repository and the SPA
  bucket are `RETAIN`.
- **The ALB listens on plain HTTP:80** and the SPA serves from a generated
  `*.cloudfront.net` name — `custom_domain_enabled` is `False` in both configs because
  there is no delegated domain. The session cookie crosses the CloudFront → ALB hop
  without TLS.
- **The database password does not rotate automatically.** Removed with the NAT Gateway;
  the managed rotation Lambda needs egress it no longer has. Manual rotation is two
  commands, in `docs/runbook.md`.
- **No alarm reaches a human.** `alarm_email` is `None` in both configs, so the three
  CloudWatch alarms fire into an SNS topic with no subscriber.

## Only if you later want GitHub Actions to deploy

Not needed for the script. `docs/runbook.md` §4 has the detail:

- GitHub environments `staging` / `production`, with a deployment-branch policy for `main`
  and required reviewers on production.
- Repository variable `AWS_ACCOUNT_ID = 963352896991`.
- `staging-deploy` must exist before `prod-deploy` — the OIDC provider is account-global.

## Full detail

`docs/runbook.md` — the deploy path, the cost trade-offs and how to reverse each, rotation,
logs, alarms, and everything still manual.
