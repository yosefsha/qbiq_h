# Deploy from GitHub Actions over OIDC, not from CodePipeline

`CLAUDE.md` specified CodePipeline with CodeStar Connections and two CodeBuild projects, and `infra/stacks/pipeline_stack.py` implemented it. That stack is deleted. Deploys now run from `.github/workflows/deploy.yml`, which assumes a role in `infra/stacks/deploy_stack.py` through GitHub's OIDC provider and holds no AWS credential at all. This is a deliberate divergence from `CLAUDE.md`, which is why it is written down here rather than substituted quietly.

## Why

**The pipeline could not start without a human in the AWS console.** `CodeStarConnectionsSourceAction` needs a connection ARN, and CDK cannot produce a usable one: the resource it creates is `PENDING` until someone completes the GitHub OAuth handshake by hand under Developer Tools → Settings → Connections. A pipeline deployed against a `PENDING` connection deploys *successfully* and then never triggers — the failure is invisible until someone notices that merging to `main` changed nothing. That step was documented as a permanent manual prerequisite in `docs/runbook.md`; the honest reading is that it was a manual prerequisite because CloudFormation has no way to automate an OAuth grant, and it will still be one in a year.

**It re-ran a test suite that had already run.** `.github/workflows/ci.yml` runs ruff, pytest against real Postgres and Redis, eslint, `vue-tsc`, vitest and both image builds on every push to `main` and every pull request. The backend CodeBuild project then ran `pytest -q` again, on the same commit, in a second environment with its own Python install and its own service containers to arrange. CodePipeline had no choice — it could not see GitHub's check results — so it paid for a second copy of the gate and doubled the time from merge to deploy. A GitHub Actions job can simply ask, which is what `deploy.yml`'s `gate` job does: one API call for the `ci.yml` conclusion on this exact SHA, and no deploy job starts until it is `success`.

**Nothing long-lived is stored anywhere.** The role is assumed with `sts:AssumeRoleWithWebIdentity` against a token GitHub mints per job and signs; there is no access key in a repository secret to leak, rotate, or forget to rotate. That is strictly better than the alternative shape of this change (an IAM user with keys in GitHub secrets), and it is the reason "move CI to GitHub" and "keep credentials out of GitHub" are not in tension.

**Two build systems is one too many.** With CodeBuild gone, every build in the project runs on the same runner image, from the same YAML dialect, with the same cache behaviour. The buildspec's `cd backend` in every phase — a CodeBuild quirk, because phases do not share a working directory — has no equivalent to get wrong.

## What is lost, stated plainly

**CodeBuild projects can be attached to a VPC; GitHub-hosted runners cannot.** A GitHub runner is a machine on the public internet, so it can reach the ALB and CloudFront, and it can reach ECR and the ECS and CloudFormation APIs — all public endpoints. It cannot reach RDS or ElastiCache, which sit in private subnets and admit only the ECS task security group (ADR-003). Exactly one thing in this project needs that reachability: `alembic upgrade head`.

The resolution is not to punch a hole in the network. It is to run the migration where the network already allows it — as a one-off Fargate task in the private subnets, with the task security group attached, from the same image being deployed. `backend_stack.py` defines a dedicated `<service>-<env>-migrate` task definition for it; the workflow renders that definition with the new image tag, runs it with `aws ecs run-task`, waits for it to stop, and fails the job on a non-zero container exit code before the service is ever updated. This is the same pattern as `docker-compose.yml`'s `migrate` service, which shares the API's image tag and which `api` waits on with `condition: service_completed_successfully` — the local and deployed shapes now match, which is the point.

Two details that pattern gets right and a naive version does not:

- **`run-task` returning 200 means the task was accepted, not that it succeeded.** The exit code has to be read separately, from `DescribeTasks`, after the task has stopped. A workflow that does not do this reports a migration that raised as a green deploy.
- **The migration gets its own task definition rather than a command override on the service's.** The service's task definition has two containers, the second being the X-Ray daemon. When the overridden application container exits, ECS stops the task and the sidecar's exit code — `137`, or absent if it never started — is reported alongside it. Any honest exit-code check looks at every container in the task, so a successful migration would fail the deploy on the sidecar's shutdown. One container, one exit code, and it means what it says.

Two smaller losses, both accepted: CodePipeline's execution history was a deploy audit trail inside AWS, which is now GitHub's Actions history plus CloudTrail entries under the `gha-*` role session names; and the manual-approval action published to an SNS topic, where GitHub's environment reviewers notify through GitHub instead.

## Considered Options

- **CodePipeline + CodeBuild, as `CLAUDE.md` specifies.** Rejected for the four reasons above. The decisive one is the CodeStar connection: a delivery mechanism whose first requirement is a console handshake that cannot be expressed in the infrastructure code, and whose failure mode when skipped is silence, is worse than one with no handshake at all.
- **Self-hosted GitHub runners inside the VPC.** This is the option that keeps every advantage above *and* recovers VPC reachability, and it is the right answer for a project that genuinely needs a runner on the private network. Rejected here because it buys back exactly one capability we do not need — the migration is solved better by an ECS task, which runs the migration from the deployed image rather than from whatever the runner has checked out — and charges a standing EC2 or ECS cost, an autoscaling controller to keep it patched, and a much larger blast radius: a self-hosted runner executes arbitrary workflow code on a host with a route to RDS. That is a considerable amount of machinery to avoid one `run-task`.
- **Deploying by hand.** Genuinely defensible for a project this size — `docker push`, `aws ecs update-service`, `aws s3 sync`, three commands — and it is still how *infrastructure* changes are applied (see below). Rejected for the application because the sequence has an ordering constraint that is invisible until it is violated: migrate before the service rolls, from the same image. A person doing this at 6pm will eventually do it in the wrong order, or from a working tree that is not the commit they think it is. The workflow encodes the order once.
- **An IAM user with an access key in GitHub secrets.** The conventional way to do this, and rejected outright: it is a credential with no expiry, readable by any workflow in the repository, that must be rotated by a process nobody owns. OIDC removes the credential rather than protecting it.
- **Deploying the CDK stacks from the workflow too.** Rejected, and the boundary is deliberate. The deploy role can push one image, run one migration task, update one ECS service, write one bucket and invalidate one distribution. A role that could also run `cdk deploy` would be able to rewrite its own trust policy, which is not a deploy role but an administrator with a YAML front end. Infrastructure changes stay a human running the CDK CLI.

## The trust policy is the security boundary

Everything above rests on IAM believing the right tokens. The trust condition is:

```json
"Condition": {
  "StringEquals": {
    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
    "token.actions.githubusercontent.com:sub": "repo:yosefsha/qbiq_h:environment:production"
  }
}
```

Both conditions are load-bearing. Without `aud`, the role accepts a token GitHub minted for any audience, rather than one minted for AWS. Without a scoped `sub` — the common `repo:yosefsha/qbiq_h:*` — every branch and every pull request in the repository can assume the role, which means anyone who can open a PR can deploy.

`sub` is scoped to a GitHub *environment* rather than a ref because every job that assumes this role declares `environment:`, and GitHub's default subject claim for such a job is `repo:<owner>/<repo>:environment:<name>` and no longer carries the ref. Adding `ref:refs/heads/main` would therefore widen the trust to a job shape that does not exist rather than narrow it to a branch.

**What IAM cannot enforce here, and what does.** A token carries one `sub`, so the trust policy cannot require branch *and* environment together. Binding the environment to `main` is the GitHub environment's deployment-branch policy — a repository setting, listed in `docs/runbook.md` as a step a human must perform, and the reason that list did not get shorter by one so much as swap a console handshake in AWS for two settings in GitHub. The workflow's `if: github.ref == 'refs/heads/main'` guard closes the same hole from the other side, but it lives in a file a branch can edit, so it is a convenience and not the control.

## Consequences

- `CLAUDE.md`'s "CI/CD Pipeline (CodePipeline + CodeBuild)" section is rewritten, and `infra/stacks/pipeline_stack.py` is deleted along with the `codestar_connection_arn` key in `infra/config/*.py`.
- The manual prerequisites moved rather than vanished. Gone: authorising a CodeStar connection in the AWS console. Added: three repository settings in GitHub — the `production` environment with its required reviewers and its deployment-branch policy, and the `AWS_ACCOUNT_ID` variable. All are in `docs/runbook.md`.
- **An IAM OIDC provider is account-global.** Staging and production share an account, so exactly one environment may create the `token.actions.githubusercontent.com` provider and the other must import it. `create_github_oidc_provider` is `True` in staging and `False` in production, which imposes a deploy order — `staging-deploy` before `prod-deploy`. Splitting the accounts removes both the flag and the ordering.
- The human gate is now a GitHub environment reviewer rather than a CodePipeline manual-approval action. It is a repository setting, so **the workflow declares the environment but cannot create the protection rule**: until someone configures reviewers, production deploys unattended. That is a worse default than the CDK-created approval action, and it is the one place this change trades an enforced property for a configured one.
- Backend and frontend remain independent: two jobs, neither `needs` the other, so a failing SPA build does not hold back an API fix.
- The deploy role reads its own stack's outputs (`cloudformation:DescribeStacks` on that stack alone) to discover the cluster, service, task-definition families, subnets, security group, bucket and distribution. No ARN is hardcoded in YAML, and a regenerated resource name does not silently break the workflow — a missing output fails the step.
- **None of this has been executed.** No AWS resource exists, so no role has ever been assumed and no deploy has ever run. `cdk synth` succeeds for both environments with no cdk-nag findings, and `actionlint` reports nothing on the workflow; that is the whole of what has been verified.
