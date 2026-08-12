"""The container registry, alone in its own stack so it can be deployed first.

This exists to break a chicken-and-egg that used to make a brand-new environment
undeployable. `backend_stack.py` renders both of its task definitions against
`<repo>:latest`. While that stack *also* created the repository, the very first
`cdk deploy <env>-backend` created an empty registry and then waited for an ECS
service whose tasks had nothing to pull: the service never stabilised, and
CloudFormation rolled the whole stack back after its timeout. The comment in
`backend_stack.py` recorded the problem and left the fix as "push an image by
hand first", which cannot be done before the repository exists.

Splitting the repository out turns that into an ordering rather than a paradox:

    <env>-ecr  ->  push an image  ->  <env>-network, <env>-data,
                                      <env>-backend, <env>-frontend, <env>-deploy

`scripts/deploy-to-aws.sh` performs exactly that order.

**References run one way.** This stack imports nothing from any other stack in
the app — no VPC, no data tier, no service. `backend_stack.py` and
`deploy_stack.py` both receive the repository as a constructor argument, so the
only edges are `backend -> ecr` and `deploy -> ecr`. Anything pointing the other
way (an output of the backend stack read here, say) would close the loop into
the `DependencyCycle` that `network_stack.py` records having bitten this project
already, and it would fail at synth rather than at deploy.
"""

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_ecr as ecr
from constructs import Construct


class EcrStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_config: dict,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        is_production = env_config["environment"] == "prod"

        self.repository = ecr.Repository(
            self,
            "BackendRepo",
            # Unchanged from when this lived in backend_stack.py, and deliberately
            # so: the repository name is the one part of a registry that people
            # and scripts type. Changing it would orphan every pushed image and
            # every `docker pull` anybody has written down.
            repository_name=f"{env_config['service_name']}-backend",
            # Production RETAINs, because a registry outlives the stack that
            # references it: destroying it would delete every image, including
            # the one currently-running tasks pull on restart, and a `cdk
            # destroy` of the API tier is not a decision to discard build
            # artefacts.
            #
            # Staging does not, because RETAIN made the environment
            # un-redeployable. `repository_name` is fixed, so a destroyed stack
            # left the repository behind and the next `cdk deploy` failed early
            # validation with "Resource of type 'AWS::ECR::Repository' with
            # identifier 'myapp-backend' already exists" — the teardown/redeploy
            # cycle `scripts/deploy-to-aws.sh` exists to make routine. Staging
            # images are rebuilt from the commit being deployed and are worth
            # nothing once the stack is gone.
            #
            # `empty_on_delete` is required for DESTROY to actually work: ECR
            # refuses to delete a repository that still holds images, so without
            # it the delete swaps one failure for another. It provisions a
            # custom resource that empties the repository first.
            removal_policy=RemovalPolicy.RETAIN if is_production else RemovalPolicy.DESTROY,
            empty_on_delete=not is_production,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=20)],
        )

        # `RepositoryUri` is what `scripts/deploy-to-aws.sh` reads to know where
        # to push, before any other stack exists. `deploy_stack.py` republishes
        # the same value as `EcrRepositoryUri` for
        # `.github/workflows/deploy.yml`, which reads the deploy stack and not
        # this one — two consumers, two contracts, deliberately not merged.
        CfnOutput(self, "RepositoryUri", value=self.repository.repository_uri)
        CfnOutput(self, "RepositoryName", value=self.repository.repository_name)

        # Environment/Service/Owner tags are applied once at the App in app.py and
        # propagate into this stack, so they are deliberately not repeated here.
