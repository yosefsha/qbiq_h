from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from aws_cdk import aws_s3 as s3
from cdk_nag import NagSuppressions
from constructs import Construct

#: Path pattern for the API behavior. The prefix is deliberately NOT stripped:
#: FastAPI mounts its routers at `/api` itself (`app/api/products.py` uses
#: `APIRouter(prefix="/api")`), and `frontend/nginx.conf` — the local equivalent
#: of this distribution — passes the path through unchanged for the same reason.
API_PATH_PATTERN = "/api/*"


class FrontendStack(Stack):
    """The SPA at the edge, with the API path-routed under the same origin.

    The `/api/*` behavior is the point of this stack, not a detail of it. It is
    what makes the browser see one host for both the SPA and the API, which is
    what allows the anonymous session cookie to stay `SameSite=Lax` instead of
    being weakened to `SameSite=None` (ADR-001). An `api.` subdomain would make
    every Cart request cross-site.

    References run frontend -> backend only. This stack reads the backend
    stack's load balancer DNS name; nothing in the backend stack refers back
    here. Reversing any part of that is the `DependencyCycle` recorded in
    `network_stack.py`.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_config: dict,
        load_balancer: elbv2.IApplicationLoadBalancer,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.bucket = s3.Bucket(
            self,
            "FrontendBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # A custom domain needs a real, delegated hosted zone: the ACM
        # certificate below is DNS-validated against it, and CloudFront will not
        # accept an alias it cannot prove ownership of. `infra/config/*.py` still
        # carries placeholder domains, so this is off by default — requesting a
        # certificate against a zone that does not exist would produce a template
        # that synthesizes and can never deploy. With it off the distribution
        # serves on its generated `*.cloudfront.net` name, which is deployable
        # today. See docs/runbook.md for the manual steps to turn it on.
        custom_domain_enabled = bool(env_config.get("custom_domain_enabled"))

        certificate = None
        hosted_zone = None
        if custom_domain_enabled:
            # CloudFront only reads viewer certificates from us-east-1. This
            # stack is deployed into `env_config["region"]`, so a non-us-east-1
            # region needs a cross-region certificate construct rather than the
            # plain `acm.Certificate` below. Fail loudly at synth instead of at
            # deploy.
            if env_config["region"] != "us-east-1":
                raise ValueError(
                    "custom_domain_enabled requires region us-east-1 for the "
                    "CloudFront viewer certificate; this environment is "
                    f"{env_config['region']}."
                )

            hosted_zone = route53.HostedZone.from_lookup(
                self, "Zone", domain_name=env_config["domain_name"]
            )

            certificate = acm.Certificate(
                self,
                "Certificate",
                domain_name=env_config["frontend_domain"],
                validation=acm.CertificateValidation.from_dns(hosted_zone),
            )

        # SPA routing, viewer-request side. `/products/8` is a client-side route,
        # not an object in the bucket, so without this S3 answers 403 (the bucket
        # blocks public access, so a missing key is AccessDenied, not NoSuchKey)
        # and the deep link breaks.
        #
        # This is a CloudFront Function rather than the distribution's
        # `error_responses`, on purpose. Custom error responses are
        # distribution-wide: a genuine `404` from the API would be rewritten into
        # the SPA shell and returned as `200 text/html`, and the frontend would
        # try to parse HTML as JSON. A function is per-behavior, so it can be
        # attached to the S3 behaviors and kept away from `/api/*`.
        #
        # The `/api/` guard below is belt and braces — the API behavior has no
        # function association at all — so that moving this function onto another
        # behavior later cannot silently swallow API responses.
        spa_function = cloudfront.Function(
            self,
            "SpaRouting",
            code=cloudfront.FunctionCode.from_inline(
                "function handler(event) {"
                "  var request = event.request;"
                "  var uri = request.uri;"
                "  if (uri.startsWith('/api/')) {"
                "    return request;"
                "  }"
                "  if (uri.endsWith('/') || !uri.includes('.')) {"
                "    request.uri = '/index.html';"
                "  }"
                "  return request;"
                "}"
            ),
        )

        immutable_cache_policy = cloudfront.CachePolicy(
            self,
            "ImmutableAssets",
            default_ttl=Duration.days(365),
            max_ttl=Duration.days(365),
            min_ttl=Duration.days(365),
            enable_accept_encoding_gzip=True,
            enable_accept_encoding_brotli=True,
        )

        # The ALB listener protocol is owned by `backend_stack.py`; this follows
        # it from config rather than hardcoding, so the two cannot drift into a
        # distribution that speaks HTTPS to a listener that only speaks HTTP (or
        # the reverse), which fails as a 502 at the edge and nowhere else.
        #
        # When this flips to HTTPS, the ALB's certificate has to cover the host
        # the viewer used: the origin request policy below forwards the viewer's
        # `Host` header, and CloudFront uses that name for SNI to the origin.
        listener_protocol = str(env_config["alb_listener_protocol"]).upper()
        if listener_protocol not in ("HTTP", "HTTPS"):
            raise ValueError(
                "alb_listener_protocol must be 'HTTP' or 'HTTPS', got "
                f"{env_config['alb_listener_protocol']!r}"
            )
        origin_is_http = listener_protocol == "HTTP"

        api_origin = origins.LoadBalancerV2Origin(
            load_balancer,
            protocol_policy=(
                cloudfront.OriginProtocolPolicy.HTTP_ONLY
                if origin_is_http
                else cloudfront.OriginProtocolPolicy.HTTPS_ONLY
            ),
            http_port=80,
            https_port=443,
            origin_ssl_protocols=[cloudfront.OriginSslPolicy.TLS_V1_2],
        )

        s3_origin = origins.S3BucketOrigin.with_origin_access_control(self.bucket)

        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            # index.html and every SPA route: no caching at the edge, so a deploy
            # is visible to returning visitors immediately rather than after a
            # TTL lapses. CACHING_DISABLED is min/max/default TTL 0.
            default_behavior=cloudfront.BehaviorOptions(
                origin=s3_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=spa_function,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
            ),
            additional_behaviors={
                # Vite emits content-hashed filenames under /assets, so a changed
                # file is a changed URL and a year-long TTL can never serve stale
                # content.
                "/assets/*": cloudfront.BehaviorOptions(
                    origin=s3_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=immutable_cache_policy,
                ),
                # The single-origin behavior ADR-001 depends on.
                #
                # CACHING_DISABLED because every response here is
                # session-specific: a Cart read is a `GET` whose body depends
                # entirely on the session cookie, so any shared cache is a Cart
                # served to the wrong Shopper.
                #
                # ALL_VIEWER because CloudFront's default forwards neither
                # cookies nor query strings to a custom origin. Without it the
                # session cookie never reaches the API, every request looks like
                # a first visit, and the Cart is silently empty for every
                # shopper. It also carries the query strings the catalogue
                # filters on, and the viewer's `Host`, so the API sees the public
                # origin rather than the ALB's internal name.
                #
                # ALLOW_ALL because the Cart is written over POST/PATCH/DELETE.
                # The default (`GET, HEAD`) would turn every Cart mutation into a
                # 405 from CloudFront that never reaches the API. Only GET and
                # HEAD are cacheable methods, and with caching disabled nothing
                # is cached regardless.
                API_PATH_PATTERN: cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                ),
            },
            # No `error_responses`: they are distribution-wide and would rewrite
            # an API 404 into the SPA shell. See the comment on `spa_function`.
            domain_names=[env_config["frontend_domain"]] if custom_domain_enabled else None,
            certificate=certificate,
        )

        if custom_domain_enabled:
            route53.ARecord(
                self,
                "AliasRecord",
                zone=hosted_zone,
                record_name=env_config["frontend_domain"],
                target=route53.RecordTarget.from_alias(
                    targets.CloudFrontTarget(self.distribution)
                ),
            )

        # Environment/Service/Owner tags are applied once at the App in app.py and
        # propagate into this stack, so they are deliberately not repeated here.

        NagSuppressions.add_resource_suppressions(
            self.bucket,
            [
                {
                    "id": "AwsSolutions-S1",
                    "reason": (
                        "S3 server access logs would need a second bucket that itself "
                        "cannot be logged, and every read of this bucket already arrives "
                        "through CloudFront. Request-level visibility belongs to "
                        "CloudFront logging, not to S3 access logs."
                    ),
                }
            ],
        )

        distribution_suppressions = [
            {
                "id": "AwsSolutions-CFR3",
                "reason": (
                    "CloudFront access logging needs a dedicated log bucket with its "
                    "own retention policy, which is not created here. Remove this "
                    "suppression when that bucket exists."
                ),
            },
            {
                "id": "AwsSolutions-CFR1",
                "reason": (
                    "The storefront is deliberately served worldwide; there is no "
                    "geographic restriction to apply."
                ),
            },
            {
                "id": "AwsSolutions-CFR2",
                "reason": (
                    "AWS WAF carries a standing monthly cost and needs a rule set "
                    "chosen against real traffic. Not justified for a catalogue that "
                    "serves only public, read-only product data and holds no "
                    "credentials."
                ),
            },
        ]

        if not custom_domain_enabled:
            distribution_suppressions.append(
                {
                    "id": "AwsSolutions-CFR4",
                    "reason": (
                        "Viewer TLS is pinned to TLSv1 by the default "
                        "*.cloudfront.net certificate, and that certificate cannot be "
                        "replaced without a real domain — `custom_domain_enabled` is "
                        "False because infra/config still carries placeholder domains "
                        "and no hosted zone exists to DNS-validate against. This is "
                        "resolved by configuration, not by code: set a real "
                        "domain_name/frontend_domain and flip the flag, and the "
                        "suppression stops applying because this branch is not taken."
                    ),
                }
            )

        if origin_is_http:
            distribution_suppressions.append(
                {
                    "id": "AwsSolutions-CFR5",
                    "reason": (
                        "The CloudFront -> ALB hop for /api/* is plain HTTP because the "
                        "ALB listener is HTTP on port 80 today: an HTTPS listener needs "
                        "an ACM certificate, which needs the real domain that "
                        "infra/config does not yet have. Stated plainly rather than "
                        "papered over — session cookies traverse this hop inside the AWS "
                        "network but not over TLS. The listener is owned by "
                        "backend_stack.py (INF-05); when it gains a certificate, set "
                        "alb_listener_protocol to 'HTTPS' in infra/config and this "
                        "suppression stops applying because this branch is not taken."
                    ),
                }
            )

        NagSuppressions.add_resource_suppressions(
            self.distribution,
            distribution_suppressions,
        )
