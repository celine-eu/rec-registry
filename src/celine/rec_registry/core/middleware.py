"""
Access policy middleware with JWT authentication and in-process policy evaluation.

Rules:
- Public paths (/health, /version, /docs, etc.): no auth required
- /me* paths: require valid JWT user
- /admin* paths: require valid JWT user + policies check
- All other paths: pass through (no auth required)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import parse_qs

from celine.sdk.audit import audit_denied
from celine.sdk.auth import JwtUser
from celine.sdk.policies import (
    Action,
    CachedPolicyEngine,
    PolicyEngine,
    PolicyInput,
    Resource,
    ResourceType,
    Subject,
    SubjectType,
)
from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Host, Match, Mount

from celine.rec_registry.core.settings import settings

logger = logging.getLogger(__name__)

REQUEST_USER_KEY = "user"

# Every refusal is recorded on `celine.audit` under an action of this service
# (REQ-0091): `rec-registry.<derived admin action>` for /admin, this one for the
# self-service paths.
AUDIT_PREFIX = "rec-registry."
SELF_SERVICE_ACTION = "rec-registry.user"

# Methods that only read. Everything else mutates and is authorized separately.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# A member's field groups written through their own route, one action each
# (REQ-0081): `PUT …/members/{mk}/<segment>` derives `members.<segment>.write`.
# The segment is a fixed route segment read at its position, never a caller's
# id, and never the body. Adding a field group is a segment here, a rule in
# `access.rego` and a scope in `celine-policies` (ADR-0011).
_MEMBER_FIELD_ROUTES = frozenset({"name", "role", "area"})

# The lookups that start from an identifier naming a person and answer what that
# person holds. Matched as the whole route segment after `/admin/lookup/`, never
# as a substring of the path.
_PERSON_LOOKUPS = frozenset({"assets-by-user-ids", "members-by-dids"})


def _wants_purge(query: str) -> bool:
    """Whether a delete asks for permanent erasure rather than deactivation.

    Read from the raw query string because the authorization decision is made
    before the route parses anything. Anything not explicitly truthy is a soft
    delete: the safe reading of an ambiguous request is the recoverable one.
    """
    return parse_qs(query).get("purge", ["false"])[-1].strip().lower() in _TRUTHY


def _community_key(path: str) -> str | None:
    """The community an ``/admin/communities/{key}…`` request names, else None.

    The audit resource is the community key, a platform id. The rest of the
    path can hold member, sensor and delivery-point ids and is never recorded.
    """
    segments = [s for s in path.split("/") if s]
    if len(segments) >= 3 and segments[:2] == ["admin", "communities"]:
        return segments[2]
    return None


def route_template(request: Request) -> str | None:
    """The template of the route this request will reach, or ``None``.

    The middleware refuses before routing, so the request carries no matched route
    yet. This resolves it the way the router will: the first route matching the
    path and the method, else the first matching the path alone (the router answers
    that one ``405``). It is the template
    (``/admin/communities/{community_key}/members/{member_key}``), never the raw path,
    which carries member, sensor and delivery-point ids. A path no route serves, or
    one under a mount, gives ``None``: the record then carries no route (REQ-0091).
    """
    router = getattr(request.scope.get("app"), "router", None)
    found = None
    for route in getattr(router, "routes", ()):
        template = getattr(route, "path_format", None)
        if not template or isinstance(route, (Mount, Host)):
            continue
        # A regex match on the path and a method check: no handler, no dependency.
        match, _ = route.matches(request.scope)
        if match is Match.FULL:
            found = template
            break
        if match is Match.PARTIAL and found is None:
            found = template
    return (request.scope.get("root_path") or "") + found if found else None


@dataclass(frozen=True)
class Decision:
    """Authorization decision."""

    allowed: bool
    reason: str | None = None


def get_current_user(request: Request) -> JwtUser | None:
    """
    Get the authenticated user from the request state.

    Usage in route handlers:
        user = get_current_user(request)
    """
    return getattr(request.state, REQUEST_USER_KEY, None)


class PolicyMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces authentication and authorization rules:

    - Public paths: no auth required
    - /me*: require valid JWT
    - /admin*: require valid JWT + in-process policy check
    - Other paths: pass through
    """

    def __init__(self, app):
        super().__init__(app)

        # Initialize in-process policy engine
        self._policy_engine: CachedPolicyEngine | None = None
        if settings.policies_enabled:
            try:
                # Create base engine
                engine = PolicyEngine(
                    policies_dir=settings.policies_dir,
                    data_dir=settings.policies_data_dir,
                )
                engine.load()

                # Wrap with cache
                self._policy_engine = CachedPolicyEngine(
                    engine=engine,
                    enabled=settings.policies_cache_enabled,
                )

                logger.info(
                    f"Policy engine initialized: "
                    f"{engine.policy_count} policies loaded, "
                    f"packages: {engine.get_packages()}"
                )
            except Exception as e:
                logger.error(f"Failed to initialize policy engine: {e}")
                raise

        logger.info(
            f"PolicyMiddleware initialized: "
            f"auth_enabled={settings.auth_enabled}, "
            f"policies_enabled={settings.policies_enabled}"
        )

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Public paths - no auth required
        if self._is_public_path(path):
            return await call_next(request)

        # /me* paths - require valid JWT
        if path.startswith("/me") or path.startswith("/user"):
            user = await self._extract_user(request)
            if user is None:
                self._audit_unauthenticated(request, SELF_SERVICE_ACTION)
                return JSONResponse(
                    {"detail": "Authentication required"},
                    status_code=401,
                )
            request.state.user = user
            return await call_next(request)

        # /admin* paths - require valid JWT + policies check
        if path.startswith("/admin"):
            action = self._get_admin_action(path, request.method, request.url.query)
            user = await self._extract_user(request)
            if user is None:
                self._audit_unauthenticated(request, AUDIT_PREFIX + action)
                return JSONResponse(
                    {"detail": "Authentication required"},
                    status_code=401,
                )
            request.state.user = user

            # Check policies if enabled
            if settings.policies_enabled:
                decision = await self._check_policies(
                    request=request,
                    user=user,
                    action=action,
                    resource_id=self._get_resource_id(path),
                )
                if not decision.allowed:
                    # Returned, not raised, and before routing: recorded here,
                    # with the method and the route template (REQ-0091).
                    audit_denied(
                        AUDIT_PREFIX + action,
                        caller=user,
                        resource=_community_key(path),
                        reason=decision.reason or "denied",
                        request=request,
                        route=route_template(request),
                    )
                    return JSONResponse(
                        {"detail": decision.reason or "Access denied"},
                        status_code=403,
                    )

            return await call_next(request)

        # All other paths - pass through, optionally extract user if token present
        if settings.auth_enabled:
            user = await self._extract_user(request)
            if user:
                request.state.user = user

        return await call_next(request)

    @staticmethod
    def _audit_unauthenticated(request: Request, action: str) -> None:
        """Record a ``401`` for a token that was presented and did not verify.

        A request carrying no token names no caller and is not recorded. The
        claims of a token that failed verification are not trusted, so the
        record names no caller either (REQ-0091). The resource is the community
        key the path names, read from the path alone as for the ``403``.
        """
        if request.headers.get(settings.auth_header_name):
            audit_denied(
                action,
                resource=_community_key(request.url.path),
                reason="token_rejected",
                request=request,
                route=route_template(request),
            )

    def _is_public_path(self, path: str) -> bool:
        """Check if path is public (no auth required)."""
        public_paths = {"/health", "/version", "/openapi.json", "/docs", "/redoc"}
        return path in public_paths or path.startswith("/docs/")

    def _get_admin_action(self, path: str, method: str, query: str = "") -> str:
        """Name the action an admin request performs.

        Derived from the path *and* the method, because reading a community and
        rewriting its members are not the same permission. While every admin
        route was a read this distinction did not exist; now that a service
        account can create members it does, and granting a writer the ability to
        read everything — or a reader the ability to write — is the kind of
        over-grant `rec-registry.admin` was already too broad for.

        `rec-registry.admin` continues to satisfy all of these: the shared scope
        matcher treats `{service}.admin` as covering `{service}.*`, so nothing
        that works today stops working.

        **Only the fixed segments of a route are read, each at its position**
        (REQ-0065). Member keys, asset keys, delivery-point ids and area keys are
        chosen by callers — an attached meter's key is `meter-<sensor id>`, and
        the sensor id is whatever is printed on the device — so a derivation
        that searched the whole path for a word would let an id containing
        `lookup`, `import` or `export` choose the action, and a holder of that
        grant would reach a write it was never given. A path matching no route
        shape derives `admin`, which only `rec-registry.admin` satisfies: such a
        request answers 404 or 405 anyway, and an unknown shape must not fall
        through to a narrower grant by accident.
        """
        segments = [s for s in path.split("/") if s]
        if not segments or segments[0] != "admin":
            return "admin"
        rest = segments[1:]
        if not rest:
            return "admin"
        head = rest[0]
        method = method.upper()

        if head == "lookup":
            # Lookups are reads; the batch ones are POSTs because they carry a
            # list, not because they change anything. Any other method on a
            # lookup path is no route at all.
            if method not in _READ_METHODS and method != "POST":
                return "admin"
            # Resolving *what a named person owns* is a different disclosure
            # from resolving which community a user or sensor belongs to, so it
            # gets its own action name. Both are granted by `rec-registry.lookup`
            # today — nothing changes — but naming them apart is what lets a
            # policy separate them later without an API change. Same reasoning
            # that split read from write below.
            #
            # `members-by-dids` resolves what a named person holds, from an
            # identifier naming that person — the same disclosure as
            # `assets-by-user-ids`, and a different one from asking which
            # community a sensor sits in. It belongs on the same action by that
            # reasoning, and would otherwise fall through to the broader
            # `lookup` by default rather than by decision.
            #
            # The route name is the one segment after `lookup`; anything beyond
            # it is a caller's id (`{user_id:path}` may itself hold slashes).
            if len(rest) == 2 and rest[1] in _PERSON_LOOKUPS:
                return "assets.lookup"
            return "lookup"

        if head == "import":
            if rest in (["import"], ["import", "yaml"]) and method == "POST":
                return "import"
            return "admin"

        if head == "export":
            if rest == ["export"] and method in _READ_METHODS:
                return "export"
            return "admin"

        if head != "communities":
            return "admin"

        if method in _READ_METHODS:
            return "read"

        # Writes are named by what they touch, read from the route's shape:
        #   communities/{ck}                                   community.write
        #   communities/{ck}/areas/{area}                      community.write
        #   communities/{ck}/areas/{area}/rename   (POST)      community.write
        #   communities/{ck}/topology/{node_id}                community.write
        #   communities/{ck}/members                           members.write
        #   communities/{ck}/members/{mk}                      members.write | .purge
        #   communities/{ck}/members/{mk}/status               members.write
        #   communities/{ck}/members/{mk}/profile  (PATCH)     members.profile.write
        #   communities/{ck}/members/{mk}/name     (PUT)       members.name.write
        #   communities/{ck}/members/{mk}/role     (PUT)       members.role.write
        #   communities/{ck}/members/{mk}/area     (PUT)       members.area.write
        #   communities/{ck}/members/{mk}/delivery-points/{id}
        #                                  (PUT, DELETE)       members.delivery_points.write
        #   communities/{ck}/members/{mk}/assets/{ak}          assets.write
        n = len(rest)
        if n == 2 or (n == 4 and rest[2] in ("areas", "topology")):
            return "community.write"
        if n == 5 and rest[2] == "areas" and rest[4] == "rename":
            # Moves an area's key with its members (REQ-0079): a community
            # write, as the area routes are. The route is a POST; any other
            # method on it is no route at all.
            if method == "POST":
                return "community.write"
            return "admin"
        if n >= 3 and rest[2] == "members":
            if n == 3:
                return "members.write"
            if n == 4:
                # Erasure is not deactivation. Deactivating a member is
                # recoverable; purging them takes their assets with it and
                # cannot be undone, so it is a grant an operator can withhold
                # from a service that otherwise manages members.
                if method == "DELETE" and _wants_purge(query):
                    return "members.purge"
                return "members.write"
            if n == 5 and rest[4] == "status":
                return "members.write"
            if n == 5 and rest[4] == "profile":
                # Role and area only (REQ-0063, REQ-0070): a narrower grant
                # than `members.write`, which the policy also accepts for it
                # (REQ-0064). The route is a PATCH; any other method on it is
                # no route at all.
                if method == "PATCH":
                    return "members.profile.write"
                return "admin"
            if n == 5 and rest[4] in _MEMBER_FIELD_ROUTES:
                # One field group, one action, one scope (REQ-0081). The
                # route is a PUT; any other method on it is no route at all.
                if method == "PUT":
                    return f"members.{rest[4]}.write"
                return "admin"
            if n == 6 and rest[4] == "delivery-points":
                # The path segment is hyphenated; the action and its scope use
                # an underscore (REQ-0081). `?replaces=` changes nothing here:
                # the query is never read for this route (REQ-0081).
                if method in ("PUT", "DELETE"):
                    return "members.delivery_points.write"
                return "admin"
            if n == 6 and rest[4] == "assets":
                return "assets.write"
        return "admin"

    def _get_resource_id(self, path: str) -> str:
        """Extract resource identifier from path."""
        return path.strip("/") or "root"

    async def _extract_user(self, request: Request) -> JwtUser | None:
        """Extract and validate user from JWT token."""
        auth_header = request.headers.get(settings.auth_header_name)
        if not auth_header:
            return None

        try:
            return JwtUser.from_token(auth_header, oidc=settings.oidc)
        except ValueError as e:
            # On a path that requires a token the refusal is recorded on
            # `celine.audit` by the caller of this method (REQ-0091).
            logger.debug(f"Invalid JWT token: {e}")
            return None
        except Exception as e:
            logger.error(f"JWT extraction error: {e}")
            return None

    async def _check_policies(
        self,
        request: Request,
        user: JwtUser,
        action: str,
        resource_id: str,
    ) -> Decision:
        """Check authorization via in-process policy evaluation."""
        if self._policy_engine is None:
            return Decision(True)

        request_id = request.headers.get("X-Request-ID", "unknown")

        # Build resource attributes
        resource_attributes = {"user_sub": user.get_username()}
        if user.email:
            resource_attributes["user_email"] = user.email

        # Extract scopes from JWT claims
        scopes = user.claims.get("scope", "")
        if isinstance(scopes, str):
            scopes = scopes.split()
        elif not isinstance(scopes, list):
            scopes = []

        # Build policy input. Scopes alone decide here (REQ-0090), so the
        # subject carries no group: a realm group grants nothing on this
        # platform, and an organisation's groups count only inside that
        # organisation, which no `/admin` action names. Flattening the two
        # levels into one list is what let one community's group act as
        # another's elsewhere.
        policy_input = PolicyInput(
            subject=Subject(
                id=user.get_username(),
                type=SubjectType.USER,
                groups=[],
                scopes=scopes,
                claims=user.claims,
            ),
            resource=Resource(
                type=ResourceType(settings.policies_resource_type),
                id=resource_id,
                attributes=resource_attributes,
            ),
            action=Action(
                name=action,
                context={},
            ),
            environment={
                "request_id": request_id,
                "timestamp": time.time(),
                "path": request.url.path,
                "method": request.method,
            },
        )

        try:
            # Evaluate policy in-process
            decision = self._policy_engine.evaluate_decision(
                policy_package=settings.policies_package,
                policy_input=policy_input,
            )

            if decision.cached:
                logger.debug(f"Policy decision from cache: allowed={decision.allowed}")
            else:
                logger.info(
                    f"Policy decision: allowed={decision.allowed}, "
                    f"reason={decision.reason}, "
                    f"policy={decision.policy}"
                )

            return Decision(
                allowed=decision.allowed,
                reason=decision.reason or None,
            )

        except Exception as e:
            logger.error(f"Policy evaluation error: {e}", exc_info=True)
            # Fail closed - deny access on error
            return Decision(False, reason="Authorization check failed")


# =============================================================================
# FastAPI Dependencies
# =============================================================================


async def require_user(request: Request) -> JwtUser:
    """FastAPI dependency that requires an authenticated user."""
    user = get_current_user(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def optional_user(request: Request) -> JwtUser | None:
    """FastAPI dependency that optionally returns the authenticated user."""
    return get_current_user(request)
