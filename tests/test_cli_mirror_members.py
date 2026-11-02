"""`mirror-members`: an intermediate environment's registry holds mirrors of the source's members.

The source registry's mirror export (REQ-0103) is read with the source's own client;
the target registry is read through its full export and written through its admin
write API. Each source member of a community and area the target has becomes a member
keyed and named by its member key, `user_id` = member key, carrying the source's area,
role, type, status and account subject, a `mirror_source` marker in `extra`, and one
meter per sensor id. Mirrors gone from the source are deactivated; members without the
marker are never written. Dry run unless `--apply`; counts only (REQ-0104).

The planning is tested as a pure function, the command against mocked HTTP, and one
round trip against the real write API on PostgreSQL. Synthetic values only.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from celine.rec_registry.cli.main import app, plan_member_mirror

runner = CliRunner()

SUB_1 = "0b6f6c3e-8d2a-4c41-9f0e-5a7d2c1b9e10"
SUB_2 = "7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f"

# Stand-ins for HMAC hashes (REQ-0105): the mirror never computes one, it copies them.
H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64

SOURCE = "https://registry.prod.example.org"
TARGET = "https://registry.staging.example.org"
ORIGIN = "registry.prod.example.org"


# =============================================================================
# Builders
# =============================================================================


def _src_member(
    key: str,
    *,
    area: str = "north",
    role: str = "consumer",
    type_: str | None = "schema:Person",
    status: str = "active",
    sensors: list[str] | None = None,
    subject: str | None = SUB_1,
    pods: list[str] | None = None,
    meter_pods: dict[str, str | None] | None = None,
) -> dict:
    """A source member; `pods`/`meter_pods` given only by a keyed source (REQ-0105)."""
    member = {
        "key": key,
        "area": area,
        "role": role,
        "type": type_,
        "status": status,
        "sensor_ids": sensors or [],
        "subject": subject,
    }
    if pods is not None or meter_pods is not None:
        member["pod_hashes"] = sorted(pods or [])
        member["meter_pod_hashes"] = dict(meter_pods or {})
    return member


def _source(*communities: tuple[str, list[dict]]) -> dict:
    return {
        "communities": [
            {
                "community": key,
                "areas": {"north": {"boundary_id": "AC000E00001", "topology_ids": []}},
                "members": members,
            }
            for key, members in communities
        ]
    }


def _tgt_member(
    *,
    user_id: str,
    area: str = "north",
    role: str = "consumer",
    type_: str | None = "schema:Person",
    status: str = "active",
    meters: dict[str, str] | None = None,
    subject: str | None = SUB_1,
    mirror: bool = True,
    name: str = "N",
    points: list[dict] | None = None,
    meter_pods: dict[str, str] | None = None,
) -> dict:
    member: dict = {
        "user_id": user_id,
        "name": name,
        "role": role,
        "area": area,
        "status": status,
    }
    if type_ is not None:
        member["type"] = type_
    if subject is not None:
        member["subject"] = subject
    if mirror:
        member["mirror_source"] = ORIGIN
    if meters:
        member["assets"] = {
            "meter": {
                key: {
                    "name": key,
                    "meter_type": "bidirectional",
                    "sensor_id": sid,
                    **({"pod": (meter_pods or {})[sid]} if sid in (meter_pods or {}) else {}),
                }
                for key, sid in meters.items()
            }
        }
    if points:
        member["delivery_points"] = points
    return member


def _hmac_point(point_id: str, *, active: bool = True) -> dict:
    """A `pod-hmac` delivery point as a previous run would have left it."""
    return {"id": point_id, "type": "pod-hmac", "active": active}


def _target(community: str, members: dict, areas: tuple[str, ...] = ("north",)) -> dict:
    return {
        "community": {
            "id": community,
            "name": community,
            "areas": {a: {"name": a} for a in areas},
        },
        "members": members,
    }


def _mirror(key: str, **kw) -> dict:
    """A target member exactly as a previous run would have left it."""
    kw.setdefault("name", key)
    return _tgt_member(user_id=key, **kw)


def _nothing_planned(plan) -> bool:
    return not (
        plan.creates or plan.updates or plan.deactivations or plan.attaches or plan.detaches
        or plan.point_adds or plan.point_removes or plan.meter_pods
    )


# =============================================================================
# The plan
# =============================================================================


class TestPlanCreates:
    def test_a_new_member_is_created_with_its_key_as_username_and_the_marker(self):
        """@verifies REQ-0104"""
        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001", role="prosumer", sensors=["s-1"])])),
            [_target("rec-a", {})],
            origin=ORIGIN,
        )

        assert plan.creates == [
            (
                "rec-a",
                "ex-00001",
                {
                    "key": "ex-00001",
                    "user_id": "ex-00001",
                    "name": "ex-00001",
                    "type": "schema:Person",
                    "role": "prosumer",
                    "area": "north",
                    "status": "active",
                    "subject": SUB_1,
                    "extra": {"mirror_source": ORIGIN},
                },
            )
        ]
        assert plan.attaches == [("rec-a", "ex-00001", "s-1")]

    def test_nothing_personal_is_in_a_create(self):
        """No DID, delivery point, assets inline or e-mail: the source never sent one,
        and the body is built from a fixed list of fields.

        @verifies REQ-0104
        """
        member = _src_member("ex-00001")
        member["user_id"] = "person@example.org"
        member["name"] = "Real Name"
        member["did"] = "did:web:x"
        member["delivery_points"] = [{"id": "IT001E00000001"}]

        plan = plan_member_mirror(
            _source(("rec-a", [member])), [_target("rec-a", {})], origin=ORIGIN
        )

        body = plan.creates[0][2]
        assert set(body) == {
            "key", "user_id", "name", "type", "role", "area", "status", "subject", "extra",
        }
        assert "person@example.org" not in json.dumps(body)
        assert "Real Name" not in json.dumps(body)

    def test_a_null_type_or_subject_is_left_out(self):
        """@verifies REQ-0104"""
        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001", type_=None, subject=None)])),
            [_target("rec-a", {})],
            origin=ORIGIN,
        )

        body = plan.creates[0][2]
        assert "type" not in body
        assert "subject" not in body


class TestPlanSkips:
    def test_a_community_the_target_lacks_is_counted_never_created(self):
        """@verifies REQ-0104"""
        plan = plan_member_mirror(
            _source(
                ("rec-a", [_src_member("ex-00001")]),
                ("rec-x", [_src_member("ex-00001"), _src_member("ex-00002")]),
            ),
            [_target("rec-a", {})],
            origin=ORIGIN,
        )

        assert [c[0] for c in plan.creates] == ["rec-a"]
        assert plan.communities_missing == 1
        assert plan.skipped_no_community == 2

    def test_an_area_the_target_lacks_is_counted_never_created(self):
        """@verifies REQ-0104"""
        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001", area="south", sensors=["s-1"])])),
            [_target("rec-a", {})],
            origin=ORIGIN,
        )

        assert _nothing_planned(plan)
        assert plan.skipped_no_area == 1

    def test_a_key_held_by_an_unmanaged_member_is_counted_and_left_alone(self):
        """@verifies REQ-0104"""
        target = _target(
            "rec-a",
            {"ex-00001": _tgt_member(user_id="someone@example.org", mirror=False, role="admin")},
        )

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001", sensors=["s-1"])])),
            [target],
            origin=ORIGIN,
        )

        assert _nothing_planned(plan)
        assert plan.skipped_unmanaged_key == 1

    def test_a_username_held_by_an_unmanaged_member_is_a_key_collision(self):
        """`user_id` is unique per community: the mirror's username is its key.

        @verifies REQ-0104
        """
        target = _target("rec-a", {"local-1": _tgt_member(user_id="ex-00001", mirror=False)})

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001")])), [target], origin=ORIGIN
        )

        assert _nothing_planned(plan)
        assert plan.skipped_unmanaged_key == 1

    def test_a_sensor_an_active_unmanaged_member_holds_anywhere_is_skipped(self):
        """@verifies REQ-0104"""
        targets = [
            _target("rec-a", {}),
            _target(
                "rec-b",
                {"local-1": _tgt_member(user_id="u@example.org", mirror=False, meters={"m": "s-1"})},
            ),
        ]

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001", sensors=["s-1", "s-2"])])),
            targets,
            origin=ORIGIN,
        )

        assert plan.attaches == [("rec-a", "ex-00001", "s-2")]
        assert plan.skipped_sensor_held == 1

    def test_an_inactive_unmanaged_holder_elsewhere_does_not_block(self):
        """Only an active member holds a sensor (REQ-0069).

        @verifies REQ-0104
        """
        targets = [
            _target("rec-a", {}),
            _target(
                "rec-b",
                {
                    "local-1": _tgt_member(
                        user_id="u@example.org", mirror=False, status="inactive",
                        meters={"meter-s-1": "s-1"},
                    )
                },
            ),
        ]

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001", sensors=["s-1"])])),
            targets,
            origin=ORIGIN,
        )

        assert plan.attaches == [("rec-a", "ex-00001", "s-1")]
        assert plan.skipped_sensor_held == 0

    def test_the_meter_key_held_by_an_inactive_unmanaged_member_here_is_skipped(self):
        """Asset keys are unique per community, whatever the holder's status.

        @verifies REQ-0104
        """
        target = _target(
            "rec-a",
            {
                "local-1": _tgt_member(
                    user_id="u@example.org", mirror=False, status="inactive",
                    meters={"meter-s-1": "s-1"},
                )
            },
        )

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001", sensors=["s-1"])])),
            [target],
            origin=ORIGIN,
        )

        assert plan.attaches == []
        assert plan.skipped_sensor_held == 1


class TestPlanUpdates:
    def test_only_the_fields_that_differ_are_patched(self):
        """@verifies REQ-0104"""
        target = _target("rec-a", {"ex-00001": _mirror("ex-00001", role="consumer")})

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001", role="prosumer", subject=SUB_2)])),
            [target],
            origin=ORIGIN,
        )

        assert plan.updates == [("rec-a", "ex-00001", {"role": "prosumer", "subject": SUB_2})]
        assert plan.creates == []

    def test_a_subject_compares_case_insensitively(self):
        """@verifies REQ-0104"""
        target = _target("rec-a", {"ex-00001": _mirror("ex-00001")})

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001", subject=SUB_1.upper())])),
            [target],
            origin=ORIGIN,
        )

        assert _nothing_planned(plan)
        assert plan.unchanged == 1

    def test_meters_follow_the_source(self):
        """@verifies REQ-0104"""
        target = _target(
            "rec-a",
            {"ex-00001": _mirror("ex-00001", meters={"meter-s-1": "s-1", "meter-s-2": "s-2"})},
        )

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001", sensors=["s-2", " s-3 "])])),
            [target],
            origin=ORIGIN,
        )

        assert plan.detaches == [("rec-a", "ex-00001", "meter-s-1")]
        assert plan.attaches == [("rec-a", "ex-00001", "s-3")]
        assert plan.updates == []


class TestPlanDeactivates:
    def test_a_mirror_gone_from_the_source_is_deactivated_never_purged(self):
        """@verifies REQ-0104"""
        target = _target(
            "rec-a",
            {
                "ex-00001": _mirror("ex-00001"),
                "ex-00002": _mirror("ex-00002"),
                "ex-00003": _mirror("ex-00003", status="inactive"),
            },
        )

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001")])), [target], origin=ORIGIN
        )

        assert plan.deactivations == [("rec-a", "ex-00002")]
        assert plan.updates == []

    def test_mirrors_of_a_community_gone_from_the_source_are_deactivated(self):
        """@verifies REQ-0104"""
        targets = [_target("rec-a", {}), _target("rec-b", {"ex-00001": _mirror("ex-00001")})]

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001")])), targets, origin=ORIGIN
        )

        assert plan.deactivations == [("rec-b", "ex-00001")]

    def test_an_unmanaged_member_is_never_deactivated(self):
        """@verifies REQ-0104"""
        target = _target("rec-a", {"local-1": _tgt_member(user_id="u@example.org", mirror=False)})

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001")])), [target], origin=ORIGIN
        )

        assert plan.deactivations == []
        assert [c[1] for c in plan.creates] == ["ex-00001"]

    def test_a_sensor_moving_from_a_gone_mirror_is_detached_first(self):
        """The gone mirror keeps its other meters; the moving one leaves it, so its
        `meter-<sensor>` key and sensor are free for the new holder.

        @verifies REQ-0104
        """
        target = _target(
            "rec-a",
            {"ex-00001": _mirror("ex-00001", meters={"meter-s-1": "s-1", "meter-s-9": "s-9"})},
        )

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00002", sensors=["s-1"])])),
            [target],
            origin=ORIGIN,
        )

        assert plan.deactivations == [("rec-a", "ex-00001")]
        assert plan.detaches == [("rec-a", "ex-00001", "meter-s-1")]
        assert plan.attaches == [("rec-a", "ex-00002", "s-1")]
        assert plan.skipped_sensor_held == 0


class TestPlanIsIdempotent:
    def test_a_target_that_already_mirrors_the_source_plans_nothing(self):
        """@verifies REQ-0104"""
        source = _source(
            (
                "rec-a",
                [
                    _src_member("ex-00001", sensors=["s-1"]),
                    _src_member("ex-00002", status="suspended", type_=None, subject=None),
                ],
            )
        )
        target = _target(
            "rec-a",
            {
                "ex-00001": _mirror("ex-00001", meters={"meter-s-1": "s-1"}),
                "ex-00002": _mirror("ex-00002", status="suspended", type_=None, subject=None),
                "ex-00003": _mirror("ex-00003", status="inactive"),
                "local-1": _tgt_member(user_id="u@example.org", mirror=False),
            },
        )

        plan = plan_member_mirror(source, [target], origin=ORIGIN)

        assert _nothing_planned(plan)
        assert plan.unchanged == 2
        assert plan.source_members == 2


class TestPlanDeliveryPoints:
    """A keyed source's hashes become `pod-hmac` delivery points and meter pods (REQ-0104)."""

    def test_a_new_members_hashes_become_points_and_its_meters_pods(self):
        """@verifies REQ-0104"""
        plan = plan_member_mirror(
            _source(("rec-a", [_src_member(
                "ex-00001", sensors=["s-1", "s-2"], pods=[H1],
                meter_pods={"s-1": H1, "s-2": None},
            )])),
            [_target("rec-a", {})],
            origin=ORIGIN,
        )

        assert plan.point_adds == [("rec-a", "ex-00001", H1)]
        assert plan.attach_pods == {("rec-a", "ex-00001", "s-1"): H1}
        assert plan.point_removes == []
        assert plan.meter_pods == []

    def test_points_follow_the_source_and_other_types_are_left_alone(self):
        """A gone hash is removed, not set inactive: an active member holds every
        point it lists whatever its flag (REQ-0085), so only a removal frees it.

        @verifies REQ-0104
        """
        cups = {"id": "ES0021000000000001AB", "type": "cups"}
        target = _target("rec-a", {"ex-00001": _mirror(
            "ex-00001", points=[_hmac_point(H1), _hmac_point(H2), cups],
        )})

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001", pods=[H2, H3])])),
            [target],
            origin=ORIGIN,
        )

        assert plan.point_adds == [("rec-a", "ex-00001", H3)]
        assert plan.point_removes == [("rec-a", "ex-00001", H1)]
        assert plan.unchanged == 0

    def test_an_inactive_point_still_wanted_is_put_again(self):
        """@verifies REQ-0104"""
        target = _target("rec-a", {"ex-00001": _mirror(
            "ex-00001", points=[_hmac_point(H1, active=False)],
        )})

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001", pods=[H1])])), [target], origin=ORIGIN
        )

        assert plan.point_adds == [("rec-a", "ex-00001", H1)]
        assert plan.point_removes == []

    def test_a_kept_meters_pod_follows_the_source(self):
        """@verifies REQ-0104"""
        target = _target("rec-a", {"ex-00001": _mirror(
            "ex-00001",
            meters={"meter-s-1": "s-1", "meter-s-2": "s-2", "meter-s-3": "s-3"},
            meter_pods={"s-1": H1, "s-2": H2},
            points=[_hmac_point(H1), _hmac_point(H2)],
        )})

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member(
                "ex-00001", sensors=["s-1", "s-2", "s-3"], pods=[H1, H3],
                meter_pods={"s-1": H1, "s-2": None, "s-3": H3},
            )])),
            [target],
            origin=ORIGIN,
        )

        assert plan.meter_pods == [
            ("rec-a", "ex-00001", "s-2", H2, None),
            ("rec-a", "ex-00001", "s-3", None, H3),
        ]
        assert plan.point_removes == [("rec-a", "ex-00001", H2)]
        assert plan.point_adds == [("rec-a", "ex-00001", H3)]

    @pytest.mark.parametrize("held_as", ["point", "meter"])
    def test_a_hash_an_active_unmanaged_member_holds_is_skipped(self, held_as):
        """REQ-0085's one active holder: counted, never written, and no meter names it.

        @verifies REQ-0104
        """
        local = _tgt_member(
            user_id="u@example.org", mirror=False,
            **({"points": [{"id": H1.upper(), "type": "pod-hmac"}]} if held_as == "point"
               else {"meters": {"meter-x": "x"}, "meter_pods": {"x": H1}}),
        )
        target = _target("rec-a", {"local-1": local})

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member(
                "ex-00001", sensors=["s-1"], pods=[H1, H2], meter_pods={"s-1": H1},
            )])),
            [target],
            origin=ORIGIN,
        )

        assert plan.skipped_pod_held == 1
        assert plan.point_adds == [("rec-a", "ex-00001", H2)]
        assert plan.attach_pods == {}

    def test_an_inactive_unmanaged_holder_does_not_block(self):
        """@verifies REQ-0104"""
        local = _tgt_member(user_id="u@example.org", mirror=False, status="inactive",
                            points=[_hmac_point(H1)])

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member("ex-00001", pods=[H1])])),
            [_target("rec-a", {"local-1": local})],
            origin=ORIGIN,
        )

        assert plan.skipped_pod_held == 0
        assert plan.point_adds == [("rec-a", "ex-00001", H1)]

    def test_a_source_without_hashes_is_counted_and_touches_no_point(self):
        """No key in the source: members and meters are mirrored, points and pods left
        as they are, and the run says so.

        @verifies REQ-0104
        """
        target = _target("rec-a", {"ex-00001": _mirror(
            "ex-00001", meters={"meter-s-1": "s-1"}, meter_pods={"s-1": H1},
            points=[_hmac_point(H1)],
        )})

        plan = plan_member_mirror(
            _source(("rec-a", [
                _src_member("ex-00001", sensors=["s-1"]),
                _src_member("ex-00002", sensors=["s-2"]),
            ])),
            [target],
            origin=ORIGIN,
        )

        assert plan.pod_hashes_absent == 2
        assert plan.point_adds == plan.point_removes == plan.meter_pods == []
        assert plan.attach_pods == {}
        assert plan.attaches == [("rec-a", "ex-00002", "s-2")]
        assert plan.unchanged == 1

    def test_a_target_that_already_holds_the_hashes_plans_nothing(self):
        """@verifies REQ-0104"""
        target = _target("rec-a", {"ex-00001": _mirror(
            "ex-00001", meters={"meter-s-1": "s-1", "meter-s-2": "s-2"},
            meter_pods={"s-1": H1}, points=[_hmac_point(H1), _hmac_point(H2)],
        )})

        plan = plan_member_mirror(
            _source(("rec-a", [_src_member(
                "ex-00001", sensors=["s-1", "s-2"], pods=[H2, H1],
                meter_pods={"s-1": H1, "s-2": None},
            )])),
            [target],
            origin=ORIGIN,
        )

        assert _nothing_planned(plan)
        assert plan.unchanged == 1
        assert plan.pod_hashes_absent == 0


# =============================================================================
# The command, against mocked HTTP
# =============================================================================

HTTPX_GET = "celine.rec_registry.cli.main.httpx.get"
HTTPX_POST = "celine.rec_registry.cli.main.httpx.post"
HTTPX_PATCH = "celine.rec_registry.cli.main.httpx.patch"
HTTPX_PUT = "celine.rec_registry.cli.main.httpx.put"
HTTPX_DELETE = "celine.rec_registry.cli.main.httpx.delete"


def _resp(status: int, *, body=None, text: str | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    r.text = text if text is not None else json.dumps(body)
    return r


class _Fake:
    """The source's mirror export, the target's full export and its writes."""

    def __init__(self, source: dict, target: list[dict], *, source_status=200,
                 target_status=200, write_status=200):
        self.source = source
        self.target = target
        self.source_status = source_status
        self.target_status = target_status
        self.write_status = write_status
        self.get = MagicMock(side_effect=self._get)
        self.writes = {
            name: MagicMock(side_effect=self._write) for name in ("post", "patch", "put", "delete")
        }

    def _get(self, url, *, params=None, headers=None, timeout=None, **_):
        if url == f"{SOURCE}/admin/export/mirror":
            body = self.source if self.source_status < 400 else {"detail": "no"}
            return _resp(self.source_status, body=body)
        assert url == f"{TARGET}/admin/export", url
        text = yaml.safe_dump_all(self.target) if self.target_status < 400 else "{}"
        return _resp(self.target_status, text=text)

    def _write(self, url, *, json=None, headers=None, timeout=None, **_):
        return _resp(self.write_status, body={})

    def write_calls(self) -> int:
        return sum(m.call_count for m in self.writes.values())

    def run(self, *args: str, source_args: tuple[str, ...] | None = None):
        if source_args is None:
            source_args = ("--source-url", SOURCE, "--source-token", "source-jwt")
        with patch(HTTPX_GET, self.get), patch(HTTPX_POST, self.writes["post"]), patch(
            HTTPX_PATCH, self.writes["patch"]
        ), patch(HTTPX_PUT, self.writes["put"]), patch(HTTPX_DELETE, self.writes["delete"]):
            return runner.invoke(
                app,
                ["mirror-members", *source_args, "--api", TARGET, "--token", "target-jwt", *args],
            )


def _counts(output: str) -> dict[str, int]:
    counts = {}
    for line in output.splitlines():
        name, _, value = line.partition("\t")
        if value.strip().isdigit():
            counts[name] = int(value)
    return counts


def _scenario() -> tuple[dict, list[dict]]:
    source = _source(
        (
            "rec-a",
            [
                _src_member("ex-00001", sensors=["s-1"]),
                _src_member("ex-00002", role="prosumer", subject=SUB_2),
            ],
        ),
        ("rec-x", [_src_member("ex-00001")]),
    )
    target = [
        _target(
            "rec-a",
            {
                "ex-00002": _mirror("ex-00002"),
                "ex-00007": _mirror("ex-00007"),
                "local-1": _tgt_member(user_id="u@example.org", mirror=False),
            },
        )
    ]
    return source, target


@pytest.fixture(autouse=True)
def _not_prod(monkeypatch):
    monkeypatch.delenv("CELINE_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)


class TestMirrorMembersCommand:
    def test_it_is_a_dry_run_unless_told_otherwise(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_scenario())

        result = fake.run()

        assert result.exit_code == 0, result.output
        assert fake.write_calls() == 0
        assert _counts(result.output) == {
            "source_members": 3,
            "would_create": 1,
            "would_update": 1,
            "would_deactivate": 1,
            "would_attach_meter": 1,
            "would_detach_meter": 0,
            "unchanged": 0,
            "communities_missing": 1,
            "skipped_no_community": 1,
            "skipped_no_area": 0,
            "skipped_unmanaged_key": 0,
            "skipped_sensor_held": 0,
            "would_add_delivery_point": 0,
            "would_remove_delivery_point": 0,
            "would_set_meter_pod": 0,
            "skipped_pod_held": 0,
            "pod_hashes_absent": 3,
            "failed": 0,
        }

    def test_each_side_is_read_with_its_own_token(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_scenario())

        fake.run()

        tokens = {c.args[0]: c.kwargs["headers"]["Authorization"] for c in fake.get.call_args_list}
        assert tokens == {
            f"{SOURCE}/admin/export/mirror": "Bearer source-jwt",
            f"{TARGET}/admin/export": "Bearer target-jwt",
        }

    def test_apply_writes_through_the_admin_api_in_order(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_scenario())
        order: list[str] = []
        for name, mock in fake.writes.items():
            mock.side_effect = (
                lambda url, *, json=None, headers=None, timeout=None, _n=name, **_: (
                    order.append(_n) or _resp(200, body={})
                )
            )

        result = fake.run("--apply")

        assert result.exit_code == 0, result.output
        post = fake.writes["post"].call_args
        assert post.args[0] == f"{TARGET}/admin/communities/rec-a/members"
        assert post.kwargs["json"]["extra"] == {"mirror_source": ORIGIN}
        assert post.kwargs["headers"]["Authorization"] == "Bearer target-jwt"
        patches = [(c.args[0], c.kwargs["json"]) for c in fake.writes["patch"].call_args_list]
        assert patches == [
            (f"{TARGET}/admin/communities/rec-a/members/ex-00007", {"status": "inactive"}),
            (
                f"{TARGET}/admin/communities/rec-a/members/ex-00002",
                {"role": "prosumer", "subject": SUB_2},
            ),
        ]
        put = fake.writes["put"].call_args
        assert put.args[0] == f"{TARGET}/admin/communities/rec-a/members/ex-00001/assets/meter-s-1"
        assert put.kwargs["json"] == {
            "key": "meter-s-1",
            "asset_type": "meter",
            "properties": {"name": "meter-s-1", "sensor_id": "s-1", "meter_type": "bidirectional"},
        }
        assert order == ["patch", "patch", "post", "put"]
        counts = _counts(result.output)
        assert (counts["created"], counts["updated"], counts["deactivated"]) == (1, 1, 1)
        assert counts["attached_meter"] == 1

    def test_it_prints_counts_and_nothing_that_names_a_member(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_scenario())

        result = fake.run("--apply")

        for value in ("ex-0000", "local-1", "u@example.org", SUB_1, SUB_2, "s-1", "rec-a"):
            assert value not in result.output

    def test_a_refused_write_is_counted_and_fails_the_run(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_scenario(), write_status=409)

        result = fake.run("--apply")

        assert result.exit_code == 1, result.output
        counts = _counts(result.output)
        assert counts["failed"] == 3
        assert counts["created"] == 0

    def test_a_meter_of_a_member_whose_create_failed_is_not_attached(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_scenario())
        fake.writes["post"].side_effect = lambda *a, **k: _resp(422, body={})

        result = fake.run("--apply")

        assert result.exit_code == 1
        fake.writes["put"].assert_not_called()

    def test_an_unreadable_source_writes_nothing(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_scenario(), source_status=403)

        result = fake.run("--apply")

        assert result.exit_code == 2
        assert fake.write_calls() == 0

    def test_an_unreadable_target_writes_nothing(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_scenario(), target_status=403)

        result = fake.run("--apply")

        assert result.exit_code == 2
        assert fake.write_calls() == 0

    def test_a_source_with_no_community_is_refused(self):
        """An empty answer is far likelier a wrong source than a source with nobody,
        and acting on it would deactivate every mirror.

        @verifies REQ-0104
        """
        fake = _Fake({"communities": []}, _scenario()[1])

        result = fake.run("--apply")

        assert result.exit_code == 2
        assert fake.write_calls() == 0

    def test_it_refuses_a_source_on_the_targets_host(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_scenario())

        result = fake.run(
            "--apply",
            source_args=("--source-url", "https://REGISTRY.staging.example.org:8443/x",
                         "--source-token", "source-jwt"),
        )

        assert result.exit_code == 2
        fake.get.assert_not_called()
        assert fake.write_calls() == 0

    @pytest.mark.parametrize(
        ("var", "value"),
        [("CELINE_ENV", "prod"), ("CELINE_ENV", "Production"), ("ENVIRONMENT", "prod")],
    )
    def test_it_refuses_to_run_in_prod(self, monkeypatch, var, value):
        """@verifies REQ-0104"""
        monkeypatch.setenv(var, value)
        fake = _Fake(*_scenario())

        result = fake.run()

        assert result.exit_code == 2
        fake.get.assert_not_called()

    def test_the_source_can_be_a_file(self, tmp_path):
        """@verifies REQ-0104"""
        source, target = _scenario()
        path = tmp_path / "mirror.json"
        path.write_text(json.dumps(source))
        fake = _Fake(source, target)

        result = fake.run("--apply", source_args=("--source-file", str(path)))

        assert result.exit_code == 0, result.output
        assert [c.args[0] for c in fake.get.call_args_list] == [f"{TARGET}/admin/export"]
        assert fake.writes["post"].call_args.kwargs["json"]["extra"] == {"mirror_source": "file"}

    def test_it_needs_exactly_one_source(self, tmp_path):
        """@verifies REQ-0104"""
        path = tmp_path / "mirror.json"
        path.write_text("{}")
        fake = _Fake(*_scenario())

        neither = fake.run(source_args=())
        both = fake.run(source_args=("--source-file", str(path), "--source-url", SOURCE))

        assert neither.exit_code == 2
        assert both.exit_code == 2
        fake.get.assert_not_called()


def _keyed_scenario() -> tuple[dict, list[dict]]:
    source = _source(
        (
            "rec-a",
            [
                _src_member("ex-00001", sensors=["s-1"], pods=[H1], meter_pods={"s-1": H1}),
                _src_member("ex-00002", sensors=["s-2"], pods=[H3], meter_pods={"s-2": H3}),
            ],
        )
    )
    target = [
        _target(
            "rec-a",
            {
                "ex-00002": _mirror(
                    "ex-00002", meters={"meter-s-2": "s-2"}, meter_pods={"s-2": H2},
                    points=[_hmac_point(H2)],
                ),
            },
        )
    ]
    return source, target


def _meter_body(sensor_id: str, pod: str | None = None) -> dict:
    properties = {"name": f"meter-{sensor_id}", "sensor_id": sensor_id,
                  "meter_type": "bidirectional"}
    if pod is not None:
        properties["pod"] = pod
    return {"key": f"meter-{sensor_id}", "asset_type": "meter", "properties": properties}


class TestMirrorMembersCommandWithHashes:
    def _recording(self, fake: _Fake) -> list[tuple[str, str, dict | None]]:
        calls: list[tuple[str, str, dict | None]] = []
        for name, mock in fake.writes.items():
            mock.side_effect = (
                lambda url, *, json=None, headers=None, timeout=None, _n=name, **_: (
                    calls.append((_n, url.removeprefix(f"{TARGET}/admin/communities/rec-a/"),
                                  json))
                    or _resp(200, body={})
                )
            )
        return calls

    def test_apply_unlinks_removes_creates_adds_then_links(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_keyed_scenario())
        calls = self._recording(fake)

        result = fake.run("--apply")

        assert result.exit_code == 0, result.output
        point = {"type": "pod-hmac", "active": True}
        assert calls == [
            ("put", "members/ex-00002/assets/meter-s-2", _meter_body("s-2")),
            ("delete", f"members/ex-00002/delivery-points/{H2}", None),
            ("post", "members", calls[2][2]),
            ("put", f"members/ex-00001/delivery-points/{H1}", {"id": H1, **point}),
            ("put", f"members/ex-00002/delivery-points/{H3}", {"id": H3, **point}),
            ("put", "members/ex-00001/assets/meter-s-1", _meter_body("s-1", H1)),
            ("put", "members/ex-00002/assets/meter-s-2", _meter_body("s-2", H3)),
        ]
        counts = _counts(result.output)
        assert counts["added_delivery_point"] == 2
        assert counts["removed_delivery_point"] == 1
        assert counts["set_meter_pod"] == 1
        assert counts["attached_meter"] == 1
        assert counts["pod_hashes_absent"] == 0

    def test_a_dry_run_counts_them(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_keyed_scenario())

        result = fake.run()

        assert result.exit_code == 0, result.output
        assert fake.write_calls() == 0
        counts = _counts(result.output)
        assert counts["would_add_delivery_point"] == 2
        assert counts["would_remove_delivery_point"] == 1
        assert counts["would_set_meter_pod"] == 1

    def test_no_hash_is_printed(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_keyed_scenario())

        result = fake.run("--apply")

        for value in (H1, H2, H3, H1[:12]):
            assert value not in result.output

    def test_a_member_whose_create_failed_gets_no_point(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_keyed_scenario())
        calls = self._recording(fake)
        fake.writes["post"].side_effect = lambda *a, **k: _resp(422, body={})

        result = fake.run("--apply")

        assert result.exit_code == 1
        assert not [c for c in calls if c[1].startswith("members/ex-00001/")]

    def test_a_source_without_hashes_still_mirrors_and_says_so(self):
        """@verifies REQ-0104"""
        fake = _Fake(*_scenario())

        result = fake.run("--apply")

        assert result.exit_code == 0, result.output
        assert _counts(result.output)["pod_hashes_absent"] == 3
        assert not [c for c in fake.writes["put"].call_args_list if "delivery-points" in c.args[0]]


# =============================================================================
# One round trip through the real write API
# =============================================================================


def _seed_bundle() -> dict:
    from tests.substations import substation_graph

    return {
        "version": "1.0",
        "schema_version": "0.7",
        "community": {"id": "mirror-rec", "name": "Mirror Community",
                      **substation_graph("north", "south")},
        "members": {
            "local-1": {
                "user_id": "local.one@example.org",
                "name": "Local One",
                "role": "consumer",
                "area": "north",
                "status": "active",
                "assets": {
                    "meter": {
                        "meter-held-1": {
                            "name": "Held", "meter_type": "consumption", "sensor_id": "held-1",
                        }
                    }
                },
            }
        },
    }


@pytest.mark.integration
class TestAgainstTheWriteApi:
    async def test_apply_then_a_second_run_plans_nothing(self, live_client, tmp_path):
        """@verifies REQ-0104"""
        r = await live_client.post(
            "/admin/import", json={"bundle": _seed_bundle(), "dry_run": False}
        )
        assert r.status_code == 200, r.text

        source = {
            "communities": [
                {
                    "community": "mirror-rec",
                    "areas": {},
                    "members": [
                        _src_member("ex-00001", role="prosumer", sensors=["m-1", "held-1"]),
                        _src_member("ex-00002", area="south", status="suspended", subject=None,
                                    type_=None, sensors=["m-2"]),
                        _src_member("local-1"),
                        _src_member("ex-00003", area="east"),
                    ],
                }
            ]
        }
        path = tmp_path / "mirror.json"
        path.write_text(json.dumps(source))

        loop = asyncio.get_running_loop()

        def bridge(method: str):
            def call(url, *, json=None, headers=None, timeout=None, params=None, **_):
                path_ = url.removeprefix("http://testserver")
                fut = asyncio.run_coroutine_threadsafe(
                    live_client.request(method, path_, json=json, params=params), loop
                )
                return fut.result(timeout=60)

            return call

        def invoke(*args: str):
            with patch(HTTPX_GET, bridge("GET")), patch(HTTPX_POST, bridge("POST")), patch(
                HTTPX_PATCH, bridge("PATCH")
            ), patch(HTTPX_PUT, bridge("PUT")), patch(HTTPX_DELETE, bridge("DELETE")):
                return runner.invoke(
                    app,
                    ["mirror-members", "--source-file", str(path),
                     "--api", "http://testserver", "--token", "t", *args],
                )

        first = await asyncio.to_thread(invoke, "--apply")
        assert first.exit_code == 0, first.output
        counts = _counts(first.output)
        assert counts["created"] == 2
        assert counts["attached_meter"] == 2
        assert counts["skipped_unmanaged_key"] == 1
        assert counts["skipped_sensor_held"] == 1
        assert counts["skipped_no_area"] == 1

        second = await asyncio.to_thread(invoke)
        assert second.exit_code == 0, second.output
        counts = _counts(second.output)
        for name in ("would_create", "would_update", "would_deactivate",
                     "would_attach_meter", "would_detach_meter"):
            assert counts[name] == 0, (name, second.output)
        assert counts["unchanged"] == 2

        r = await live_client.get("/admin/export", params={"community": "mirror-rec"})
        doc = yaml.safe_load(r.text)
        one = doc["members"]["ex-00001"]
        assert one["user_id"] == "ex-00001"
        assert one["name"] == "ex-00001"
        assert one["subject"] == SUB_1
        assert one["mirror_source"] == "file"
        assert "did" not in one and not one.get("delivery_points")
        assert sorted(m["sensor_id"] for m in one["assets"]["meter"].values()) == ["m-1"]
        assert doc["members"]["ex-00002"]["status"] == "suspended"
        local = doc["members"]["local-1"]
        assert local["user_id"] == "local.one@example.org"
        assert "mirror_source" not in local

        # Gone from the source: deactivated, its row and meters kept.
        source["communities"][0]["members"] = [_src_member("ex-00002", area="south",
                                                           status="suspended", subject=None,
                                                           type_=None, sensors=["m-2"])]
        path.write_text(json.dumps(source))
        third = await asyncio.to_thread(invoke, "--apply")
        assert third.exit_code == 0, third.output
        assert _counts(third.output)["deactivated"] == 1
        r = await live_client.get("/admin/export", params={"community": "mirror-rec"})
        doc = yaml.safe_load(r.text)
        assert doc["members"]["ex-00001"]["status"] == "inactive"
        assert doc["members"]["local-1"]["status"] == "active"


@pytest.mark.integration
class TestHashesAgainstTheWriteApi:
    async def test_points_and_pods_round_trip_and_move(self, live_client, tmp_path):
        """@verifies REQ-0104"""
        held = "4" * 64
        bundle = _seed_bundle()
        bundle["members"]["local-1"]["delivery_points"] = [{"id": held, "type": "pod-hmac"}]
        r = await live_client.post("/admin/import", json={"bundle": bundle, "dry_run": False})
        assert r.status_code == 200, r.text

        def write_source(*members: dict) -> None:
            path.write_text(json.dumps({"communities": [
                {"community": "mirror-rec", "areas": {}, "members": list(members)}
            ]}))

        path = tmp_path / "mirror.json"
        write_source(
            _src_member("ex-00001", sensors=["m-1"], pods=[H1, held], meter_pods={"m-1": H1}),
            _src_member("ex-00002", area="south", sensors=["m-2"], pods=[H2],
                        meter_pods={"m-2": H2}),
        )

        loop = asyncio.get_running_loop()

        def bridge(method: str):
            def call(url, *, json=None, headers=None, timeout=None, params=None, **_):
                fut = asyncio.run_coroutine_threadsafe(
                    live_client.request(method, url.removeprefix("http://testserver"),
                                        json=json, params=params),
                    loop,
                )
                return fut.result(timeout=60)

            return call

        def invoke(*args: str):
            with patch(HTTPX_GET, bridge("GET")), patch(HTTPX_POST, bridge("POST")), patch(
                HTTPX_PATCH, bridge("PATCH")
            ), patch(HTTPX_PUT, bridge("PUT")), patch(HTTPX_DELETE, bridge("DELETE")):
                return runner.invoke(
                    app,
                    ["mirror-members", "--source-file", str(path),
                     "--api", "http://testserver", "--token", "t", *args],
                )

        async def members() -> dict:
            r = await live_client.get("/admin/export", params={"community": "mirror-rec"})
            return yaml.safe_load(r.text)["members"]

        def pod_of(member: dict, sensor_id: str):
            meters = member["assets"]["meter"].values()
            return next(m for m in meters if m["sensor_id"] == sensor_id).get("pod")

        first = await asyncio.to_thread(invoke, "--apply")
        assert first.exit_code == 0, first.output
        counts = _counts(first.output)
        assert (counts["created"], counts["added_delivery_point"]) == (2, 2)
        assert counts["skipped_pod_held"] == 1
        assert counts["attached_meter"] == 2

        doc = await members()
        assert doc["ex-00001"]["delivery_points"] == [
            {"id": H1, "type": "pod-hmac", "active": True}
        ]
        assert pod_of(doc["ex-00001"], "m-1") == H1
        assert pod_of(doc["ex-00002"], "m-2") == H2
        assert doc["local-1"]["delivery_points"] == [
            {"id": held, "type": "pod-hmac", "active": True}
        ]

        second = await asyncio.to_thread(invoke)
        assert second.exit_code == 0, second.output
        counts = _counts(second.output)
        for name in ("would_create", "would_update", "would_attach_meter",
                     "would_add_delivery_point", "would_remove_delivery_point",
                     "would_set_meter_pod"):
            assert counts[name] == 0, (name, second.output)
        assert counts["unchanged"] == 2

        # A hash moves between two active mirrors, and a meter's pod changes.
        write_source(
            _src_member("ex-00001", sensors=["m-1"], pods=[H2, H3], meter_pods={"m-1": H3}),
            _src_member("ex-00002", area="south", sensors=["m-2"], pods=[],
                        meter_pods={"m-2": None}),
        )
        third = await asyncio.to_thread(invoke, "--apply")
        assert third.exit_code == 0, third.output
        counts = _counts(third.output)
        assert counts["removed_delivery_point"] == 2
        assert counts["added_delivery_point"] == 2
        assert counts["set_meter_pod"] == 2
        assert counts["failed"] == 0

        doc = await members()
        assert sorted(p["id"] for p in doc["ex-00001"]["delivery_points"]) == [H2, H3]
        assert not doc["ex-00002"].get("delivery_points")
        assert pod_of(doc["ex-00001"], "m-1") == H3
        assert pod_of(doc["ex-00002"], "m-2") is None

        fourth = await asyncio.to_thread(invoke)
        counts = _counts(fourth.output)
        assert counts["unchanged"] == 2, fourth.output
