"""
Keep sensor ids, user ids and delivery-point ids out of the access log (REQ-0080).

A meter's asset key is ``meter-<sensor_id>``, and three routes take the
sensor id itself as a path segment, so uvicorn's access line — which prints the
request path and query — would carry a member's sensor id for every attach,
detach and lookup. Likewise three routes take a member's user id (their
Keycloak username) and three a delivery-point id (a POD) in the path. The image
runs uvicorn directly (Dockerfile ``CMD``), whose access line is logged to
``uvicorn.access`` with the arguments
``(client_addr, method, path_with_query, http_version, status_code)``.

A filter on that logger rewrites the path argument: the segment after
``/assets/`` becomes ``{asset_key}``, everything after ``by-sensor-id/`` becomes
``{sensor_id}``, everything after ``by-user-id/`` becomes ``{user_id}``, and
everything after ``/delivery-points/by-id/`` or
``community-by-delivery-point/``, and the segment after a member's
``/delivery-points/``, becomes ``{dp_id}``. The ``cursor`` of the asset, meter
and delivery-point listings (an asset key or a delivery-point id), and any
``sensor_id``, ``user_id`` or delivery-point id query value, becomes
``{redacted}``. Method, route shape and status are kept. The markers are fixed
rather than a hash: these ids are few, and a hash of one is reversible by
trying them.
"""

from __future__ import annotations

import logging
import re

ACCESS_LOGGER = "uvicorn.access"

ASSET_KEY_MARKER = "{asset_key}"
SENSOR_ID_MARKER = "{sensor_id}"
USER_ID_MARKER = "{user_id}"
DP_ID_MARKER = "{dp_id}"
QUERY_MARKER = "{redacted}"

# Routes whose id is a `:path` parameter, so it runs to the end of the path,
# slashes included. Rewritten first: a tail replaced here is never read again.
_PATH_TAILS = (
    # `…/assets/by-sensor-id/<id>`, `/lookup/community-by-sensor-id/<id>`,
    # `/lookup/asset-by-sensor-id/<id>`.
    (re.compile(r"(by-sensor-id/)[^?#]*"), SENSOR_ID_MARKER),
    # `…/members/by-user-id/<id>`, `/lookup/community-by-user-id/<id>`,
    # `/lookup/member-by-user-id/<id>`.
    (re.compile(r"(by-user-id/)[^?#]*"), USER_ID_MARKER),
    # `…/delivery-points/by-id/<id>`, `/lookup/community-by-delivery-point/<id>`.
    (re.compile(r"(/delivery-points/by-id/)[^?#]*"), DP_ID_MARKER),
    (re.compile(r"(community-by-delivery-point/)[^?#]*"), DP_ID_MARKER),
)
# `/assets/<key>` on the admin read, the member asset write and `/user/assets`,
# and `/delivery-points/<id>` on the member delivery-point write. No route has
# anything after the key or id, so the rest of the path is it (one with a slash
# in it 404s, and would still be logged whole otherwise).
_ASSET_KEY_IN_PATH = re.compile(r"(/assets/)(?!by-sensor-id/)[^?#]+")
_DP_ID_IN_PATH = re.compile(r"(/delivery-points/)(?!by-id/)[^?#]+")
# Listings whose pagination cursor is an asset key or a delivery-point id.
_ID_CURSOR_LISTING = re.compile(r"/(assets|meters|delivery-points)/?$")

_ALWAYS_REDACTED_PARAMS = frozenset(
    {
        "sensor_id",
        "sensor_ids",
        "user_id",
        "user_ids",
        "dp_id",
        "dp_ids",
        "delivery_point_id",
        "delivery_point_ids",
    }
)


def _redact_query(path: str, query: str) -> str:
    redact = set(_ALWAYS_REDACTED_PARAMS)
    if _ID_CURSOR_LISTING.search(path):
        redact.add("cursor")
    parts = []
    for part in query.split("&"):
        name, sep, _ = part.partition("=")
        if sep and name in redact:
            parts.append(f"{name}={QUERY_MARKER}")
        else:
            parts.append(part)
    return "&".join(parts)


def redact_path(path_with_query: str) -> str:
    """The request target as it may be logged: no asset key, sensor id, user
    id or delivery-point id."""
    path, sep, query = path_with_query.partition("?")
    for pattern, marker in _PATH_TAILS:
        path = pattern.sub(lambda m, marker=marker: m.group(1) + marker, path)
    path = _ASSET_KEY_IN_PATH.sub(lambda m: m.group(1) + ASSET_KEY_MARKER, path)
    path = _DP_ID_IN_PATH.sub(lambda m: m.group(1) + DP_ID_MARKER, path)
    if sep:
        return f"{path}?{_redact_query(path, query)}"
    return path


class AccessLogRedactor(logging.Filter):
    """Rewrites the path argument of uvicorn's access line; drops nothing."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], redact_path(args[2]), *args[3:])
        return True


def install_access_log_redaction(logger_name: str = ACCESS_LOGGER) -> None:
    """Attach the redactor to the access logger, once.

    Called from ``create_app``. uvicorn configures logging before it loads the
    app factory (in reloader and worker subprocesses too), so the filter is not
    reset by that configuration.
    """
    logger = logging.getLogger(logger_name)
    if not any(isinstance(f, AccessLogRedactor) for f in logger.filters):
        logger.addFilter(AccessLogRedactor())
