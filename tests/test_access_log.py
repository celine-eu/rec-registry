"""The access log carries no sensor id, user id or delivery-point id (REQ-0080).

A meter's asset key is `meter-<sensor_id>`, and three routes take the
sensor id itself as a path segment; three take a member's user id and three a
delivery-point id. The image runs uvicorn, whose access line prints the request
path and query, so without redaction every attach, detach and lookup would
write a member's identifiers to the log.

The pure tests pin the rewrite, route by route. The live tests run a real
uvicorn server on a loopback port, loading `create_app` as a factory the way
the image's `CMD` does — so uvicorn has configured its logging before the app
installs the filter — and read the access lines it actually wrote.

Fixtures are generic: `example-rec`, `ex-0000n`, `SEN-…`, `user-…`, `DP-…`.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from celine.rec_registry.core.access_log import (
    ACCESS_LOGGER,
    AccessLogRedactor,
    install_access_log_redaction,
    redact_path,
)
from tests.substations import substation_graph

# Distinctive, so a substring check cannot pass by accident.
SENSOR = "SEN-9f41c7"
KEY = f"meter-{SENSOR}"
USER = "user-5b20ae"
DP = "DP-e37d14"
C = "example-rec"


# =============================================================================
# The rewrite
# =============================================================================


class TestRedactPath:
    @pytest.mark.parametrize(
        "raw, logged",
        [
            (
                f"/admin/communities/{C}/members/ex-00001/assets/{KEY}",
                f"/admin/communities/{C}/members/ex-00001/assets/{{asset_key}}",
            ),
            (
                f"/admin/communities/{C}/assets/{KEY}",
                f"/admin/communities/{C}/assets/{{asset_key}}",
            ),
            (f"/user/assets/{KEY}", "/user/assets/{asset_key}"),
            (
                f"/admin/communities/{C}/assets/by-sensor-id/{SENSOR}",
                f"/admin/communities/{C}/assets/by-sensor-id/{{sensor_id}}",
            ),
            (
                f"/admin/lookup/community-by-sensor-id/{SENSOR}",
                "/admin/lookup/community-by-sensor-id/{sensor_id}",
            ),
            (
                f"/admin/lookup/asset-by-sensor-id/{SENSOR}",
                "/admin/lookup/asset-by-sensor-id/{sensor_id}",
            ),
            # `:path` parameters: a slash in the id is still the id.
            (
                f"/admin/lookup/asset-by-sensor-id/a/{SENSOR}",
                "/admin/lookup/asset-by-sensor-id/{sensor_id}",
            ),
            (
                f"/admin/communities/{C}/assets/{KEY}/x",
                f"/admin/communities/{C}/assets/{{asset_key}}",
            ),
        ],
    )
    def test_the_asset_key_and_the_sensor_id_leave_the_path(self, raw, logged):
        """@verifies REQ-0080"""
        assert redact_path(raw) == logged
        assert SENSOR not in redact_path(raw)

    @pytest.mark.parametrize(
        "raw, logged",
        [
            (
                f"/admin/communities/{C}/members/by-user-id/{USER}",
                f"/admin/communities/{C}/members/by-user-id/{{user_id}}",
            ),
            (
                f"/admin/lookup/community-by-user-id/{USER}",
                "/admin/lookup/community-by-user-id/{user_id}",
            ),
            (
                f"/admin/lookup/member-by-user-id/{USER}",
                "/admin/lookup/member-by-user-id/{user_id}",
            ),
            # `:path` parameter: a slash in the id is still the id.
            (
                f"/admin/lookup/member-by-user-id/a/{USER}",
                "/admin/lookup/member-by-user-id/{user_id}",
            ),
            (
                f"/admin/communities/{C}/delivery-points/by-id/{DP}",
                f"/admin/communities/{C}/delivery-points/by-id/{{dp_id}}",
            ),
            (
                f"/admin/communities/{C}/delivery-points/by-id/a/{DP}",
                f"/admin/communities/{C}/delivery-points/by-id/{{dp_id}}",
            ),
            (
                f"/admin/lookup/community-by-delivery-point/{DP}",
                "/admin/lookup/community-by-delivery-point/{dp_id}",
            ),
            (
                f"/admin/lookup/community-by-delivery-point/a/{DP}",
                "/admin/lookup/community-by-delivery-point/{dp_id}",
            ),
            # The member delivery-point `PUT` and `DELETE`.
            (
                f"/admin/communities/{C}/members/ex-00001/delivery-points/{DP}",
                f"/admin/communities/{C}/members/ex-00001/delivery-points/{{dp_id}}",
            ),
        ],
    )
    def test_the_user_id_and_the_delivery_point_id_leave_the_path(self, raw, logged):
        """@verifies REQ-0080"""
        assert redact_path(raw) == logged
        assert USER not in redact_path(raw)
        assert DP not in redact_path(raw)

    def test_the_query_survives_a_redacted_path(self):
        """@verifies REQ-0080"""
        assert (
            redact_path(f"/admin/lookup/asset-by-sensor-id/{SENSOR}?x=1")
            == "/admin/lookup/asset-by-sensor-id/{sensor_id}?x=1"
        )

    @pytest.mark.parametrize("listing", ["assets", "meters"])
    def test_an_asset_listing_cursor_is_redacted(self, listing):
        """The cursor of these two listings is an asset key.

        @verifies REQ-0080
        """
        raw = f"/admin/communities/{C}/{listing}?limit=1&cursor={KEY}&owner=ex-00001"
        assert redact_path(raw) == (
            f"/admin/communities/{C}/{listing}?limit=1&cursor={{redacted}}&owner=ex-00001"
        )

    def test_a_delivery_point_listing_cursor_is_redacted(self):
        """The cursor of the community's delivery-point listing is a delivery-point id.

        @verifies REQ-0080
        """
        raw = f"/admin/communities/{C}/delivery-points?type=pod&cursor={DP}"
        assert redact_path(raw) == (
            f"/admin/communities/{C}/delivery-points?type=pod&cursor={{redacted}}"
        )

    def test_another_listing_keeps_its_cursor(self):
        """A member listing's cursor is a member key, not a sensor id.

        @verifies REQ-0080
        """
        raw = f"/admin/communities/{C}/members?cursor=ex-00001"
        assert redact_path(raw) == raw

    def test_a_sensor_id_query_value_is_redacted_anywhere(self):
        """@verifies REQ-0080"""
        assert (
            redact_path(f"/anything?sensor_id={SENSOR}&sensor_ids={SENSOR}")
            == "/anything?sensor_id={redacted}&sensor_ids={redacted}"
        )

    @pytest.mark.parametrize(
        "name",
        ["user_id", "user_ids", "dp_id", "dp_ids", "delivery_point_id", "delivery_point_ids"],
    )
    def test_a_user_or_delivery_point_id_query_value_is_redacted_anywhere(self, name):
        """@verifies REQ-0080"""
        assert (
            redact_path(f"/anything?limit=1&{name}={USER}")
            == f"/anything?limit=1&{name}={{redacted}}"
        )

    def test_the_duplicates_read_is_a_route_not_an_id(self):
        """`…/delivery-points/duplicates` (REQ-0087) is a fixed segment and is
        logged as it is; a member's delivery point named `duplicates` is still
        an id.

        @verifies REQ-0080
        """
        path = f"/admin/communities/{C}/delivery-points/duplicates"
        assert redact_path(path) == path
        assert (
            redact_path(f"/admin/communities/{C}/members/ex-00001/delivery-points/duplicates")
            == f"/admin/communities/{C}/members/ex-00001/delivery-points/{{dp_id}}"
        )
        assert (
            redact_path(f"/admin/communities/{C}/delivery-points/duplicates/{DP}")
            == f"/admin/communities/{C}/delivery-points/{{dp_id}}"
        )

    def test_the_pod_a_correction_replaces_is_redacted(self):
        """`PUT …/delivery-points/{new}?replaces={old}` (REQ-0084) carries two
        PODs: the new one in the path and the old one in the query.

        @verifies REQ-0080
        """
        old = "DP-0ld9a2"
        raw = f"/admin/communities/{C}/members/ex-00001/delivery-points/{DP}?replaces={old}"
        logged = redact_path(raw)
        assert logged == (
            f"/admin/communities/{C}/members/ex-00001/delivery-points/{{dp_id}}"
            "?replaces={redacted}"
        )
        assert DP not in logged and old not in logged

    @pytest.mark.parametrize(
        "raw",
        [
            "/health",
            f"/admin/communities/{C}/assets",
            f"/admin/communities/{C}/members/ex-00001",
            "/admin/lookup/assets-by-sensor-ids",
            "/admin/lookup/assets-by-user-ids",
            f"/admin/communities/{C}/delivery-points",
            f"/admin/communities/{C}/members/ex-00001/delivery-points",
            "/user/delivery-points",
        ],
    )
    def test_a_path_without_one_is_unchanged(self, raw):
        """@verifies REQ-0080"""
        assert redact_path(raw) == raw

    def test_the_line_keeps_its_arguments_and_is_never_dropped(self):
        """uvicorn's formatter unpacks five arguments; the filter keeps five.

        @verifies REQ-0080
        """
        record = logging.LogRecord(
            ACCESS_LOGGER,
            logging.INFO,
            __file__,
            1,
            '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1:5000", "PUT", f"/user/assets/{KEY}", "1.1", 200),
            None,
        )
        assert AccessLogRedactor().filter(record) is True
        assert record.args == (
            "127.0.0.1:5000",
            "PUT",
            "/user/assets/{asset_key}",
            "1.1",
            200,
        )

    def test_installing_twice_adds_one_filter(self):
        """`create_app` runs once per worker, and many times in a test run.

        @verifies REQ-0080
        """
        name = "tests.access_log.install_twice"
        install_access_log_redaction(name)
        install_access_log_redaction(name)
        filters = logging.getLogger(name).filters
        assert sum(isinstance(f, AccessLogRedactor) for f in filters) == 1


# =============================================================================
# The line uvicorn writes
# =============================================================================


class _Lines(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def _bundle() -> dict:
    return {
        "version": "1.0",
        "schema_version": "0.6",
        "community": {
            "id": C,
            "name": "Example Community",
            **substation_graph("north", "south"),
        },
        "members": {
            "ex-00001": {
                "user_id": USER,
                "name": "Example Member",
                "role": "consumer",
                "area": "north",
                "status": "active",
                "delivery_points": [{"id": DP, "type": "pod"}],
            }
        },
    }


@pytest.fixture
async def served(pg_engine):
    """A real uvicorn server running `create_app` as a factory, and its access lines.

    The policy middleware is taken out (the suite runs without a token issuer),
    and the session is the live schema's; everything else is `create_app`'s.
    """
    import uvicorn
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from celine.rec_registry.core.middleware import PolicyMiddleware
    from celine.rec_registry.db.session import get_session
    from celine.rec_registry.main import create_app

    # Prove `create_app` installs the filter, not an earlier test.
    access = logging.getLogger(ACCESS_LOGGER)
    for f in [f for f in access.filters if isinstance(f, AccessLogRedactor)]:
        access.removeFilter(f)

    maker = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def override_session():
        async with maker() as session:
            yield session

    def factory():
        app = create_app()
        app.user_middleware = [
            m for m in app.user_middleware if m.cls is not PolicyMiddleware
        ]
        app.dependency_overrides[get_session] = override_session
        return app

    # Default log config, as the image runs it: uvicorn configures its loggers
    # here, before it loads the factory.
    config = uvicorn.Config(
        factory, factory=True, host="127.0.0.1", port=0, lifespan="off"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started, "uvicorn did not start"
    port = server.servers[0].sockets[0].getsockname()[1]

    # Added after uvicorn's logging config, which replaces the logger's handlers.
    lines = _Lines()
    access.addHandler(lines)
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            yield client, lines.lines
    finally:
        access.removeHandler(lines)
        server.should_exit = True
        await task


@pytest.mark.integration
class TestTheAccessLine:
    async def test_an_attach_and_a_lookup_log_no_sensor_id(self, served):
        """@verifies REQ-0080"""
        client, lines = served
        r = await client.post("/admin/import", json={"bundle": _bundle()})
        assert r.status_code == 200, r.text

        r = await client.put(
            f"/admin/communities/{C}/members/ex-00001/assets/{KEY}",
            json={
                "key": KEY,
                "asset_type": "meter",
                "properties": {
                    "name": "Meter",
                    "sensor_id": SENSOR,
                    "meter_type": "consumption",
                },
            },
        )
        assert r.status_code in (200, 201), r.text
        requests = [
            ("GET", f"/admin/lookup/asset-by-sensor-id/{SENSOR}"),
            ("GET", f"/admin/lookup/community-by-sensor-id/{SENSOR}"),
            ("GET", f"/admin/communities/{C}/assets/by-sensor-id/{SENSOR}"),
            ("GET", f"/admin/communities/{C}/assets/{KEY}"),
            ("GET", f"/admin/communities/{C}/meters?limit=1&cursor={KEY}"),
            ("DELETE", f"/admin/communities/{C}/members/ex-00001/assets/{KEY}"),
        ]
        for method, url in requests:
            r = await client.request(method, url)
            assert r.status_code < 500, (url, r.text)

        # uvicorn writes the line after the response; let the last one land.
        for _ in range(100):
            if len(lines) >= 2 + len(requests):
                break
            await asyncio.sleep(0.01)

        assert len(lines) == 2 + len(requests), lines
        assert not [line for line in lines if SENSOR in line], lines

        # Method, route shape and status are kept.
        joined = "\n".join(lines)
        assert (
            f'"PUT /admin/communities/{C}/members/ex-00001/assets/{{asset_key}} HTTP/1.1" 20'
            in joined
        )
        assert (
            '"GET /admin/lookup/asset-by-sensor-id/{sensor_id} HTTP/1.1" 200' in joined
        )
        assert (
            '"GET /admin/lookup/community-by-sensor-id/{sensor_id} HTTP/1.1" 200'
            in joined
        )
        assert (
            f'"GET /admin/communities/{C}/meters?limit=1&cursor={{redacted}} HTTP/1.1" 200'
            in joined
        )
        assert (
            f'"DELETE /admin/communities/{C}/members/ex-00001/assets/{{asset_key}} HTTP/1.1" 20'
            in joined
        )

    async def test_a_user_and_a_delivery_point_lookup_log_no_id(self, served):
        """@verifies REQ-0080"""
        client, lines = served
        r = await client.post("/admin/import", json={"bundle": _bundle()})
        assert r.status_code == 200, r.text

        requests = [
            ("GET", f"/admin/communities/{C}/members/by-user-id/{USER}"),
            ("GET", f"/admin/lookup/community-by-user-id/{USER}"),
            ("GET", f"/admin/lookup/member-by-user-id/{USER}"),
            ("GET", f"/admin/communities/{C}/delivery-points/by-id/{DP}"),
            ("GET", f"/admin/lookup/community-by-delivery-point/{DP}"),
            ("GET", f"/admin/communities/{C}/delivery-points?limit=1&cursor={DP}"),
            (
                "DELETE",
                f"/admin/communities/{C}/members/ex-00001/delivery-points/{DP}",
            ),
        ]
        for method, url in requests:
            r = await client.request(method, url)
            assert r.status_code == 200 or (method == "DELETE" and r.status_code < 300), (
                url,
                r.status_code,
                r.text,
            )

        for _ in range(100):
            if len(lines) >= 1 + len(requests):
                break
            await asyncio.sleep(0.01)

        assert len(lines) == 1 + len(requests), lines
        assert not [line for line in lines if USER in line or DP in line], lines

        joined = "\n".join(lines)
        for logged in (
            f'"GET /admin/communities/{C}/members/by-user-id/{{user_id}} HTTP/1.1" 200',
            '"GET /admin/lookup/community-by-user-id/{user_id} HTTP/1.1" 200',
            '"GET /admin/lookup/member-by-user-id/{user_id} HTTP/1.1" 200',
            f'"GET /admin/communities/{C}/delivery-points/by-id/{{dp_id}} HTTP/1.1" 200',
            '"GET /admin/lookup/community-by-delivery-point/{dp_id} HTTP/1.1" 200',
            f'"GET /admin/communities/{C}/delivery-points?limit=1&cursor={{redacted}} HTTP/1.1" 200',
            f'"DELETE /admin/communities/{C}/members/ex-00001/delivery-points/{{dp_id}} HTTP/1.1" 20',
        ):
            assert logged in joined, (logged, lines)

    async def test_a_refused_request_logs_no_sensor_id_either(self, served):
        """An unknown community answers 404; the line is redacted all the same.

        @verifies REQ-0080
        """
        client, lines = served
        r = await client.get(f"/admin/communities/nowhere/assets/{KEY}")
        assert r.status_code == 404
        for _ in range(100):
            if lines:
                break
            await asyncio.sleep(0.01)
        assert len(lines) == 1, lines
        assert lines[0].endswith(
            '"GET /admin/communities/nowhere/assets/{asset_key} HTTP/1.1" 404'
        ), lines
