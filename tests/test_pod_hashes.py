"""PODs leave the registry only as HMAC hashes, under a key only this registry holds.

With `POD_HMAC_KEY` set, both `GET /admin/export/members` (REQ-0100) and
`GET /admin/export/mirror` (REQ-0103) add per member `pod_hashes` — the sorted
HMAC-SHA256 of its active delivery points' ids — and `meter_pod_hashes`, each meter's
`pod` hashed the same way, by sensor id. The id is normalised first: every whitespace
character removed, upper-cased. Without the key neither field is there at all; a key
shorter than 32 characters refuses to start the service. No raw POD reaches either
export, keyed or not (REQ-0105).

Synthetic values only: placeholder PODs and a test key.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest
from celine.rec_registry.core.pod_hash import pod_hmac
from pydantic import SecretStr, ValidationError

from celine.rec_registry.core.settings import Settings
from tests.test_member_export import PERSONAL, _bundle

KEY = "test-only-pod-hmac-key-0123456789abcdef"


def _expected(pod: str, key: str = KEY) -> str:
    return hmac.new(key.encode("utf-8"), pod.encode("utf-8"), hashlib.sha256).hexdigest()


class TestTheHash:
    def test_it_is_hmac_sha256_hex_of_the_id(self):
        """@verifies REQ-0105"""
        digest = pod_hmac(KEY, "IT001E00000001")

        assert digest == _expected("IT001E00000001")
        assert len(digest) == 64
        assert digest == digest.lower()

    def test_a_fixed_vector(self):
        """A value the pipelines side can check its own implementation against.

        @verifies REQ-0105
        """
        assert pod_hmac("k" * 32, "IT001E00000001") == _expected("IT001E00000001", "k" * 32)

    @pytest.mark.parametrize(
        "spelling",
        ["IT001E00000001", "it001e00000001", " IT001E00000001 ", "IT001E 0000\t0001\n",
         "It001e00000001 "],
    )
    def test_whitespace_is_removed_and_case_ignored(self, spelling):
        """@verifies REQ-0105"""
        assert pod_hmac(KEY, spelling) == _expected("IT001E00000001")

    @pytest.mark.parametrize("blank", ["", "   ", None, 42])
    def test_a_blank_or_non_string_id_has_no_hash(self, blank):
        """@verifies REQ-0105"""
        assert pod_hmac(KEY, blank) is None

    def test_another_key_gives_another_hash(self):
        """@verifies REQ-0105"""
        assert pod_hmac(KEY, "IT001E00000001") != pod_hmac(KEY + "x", "IT001E00000001")


class TestTheSetting:
    def test_unset_is_none(self, monkeypatch):
        """@verifies REQ-0105"""
        monkeypatch.delenv("POD_HMAC_KEY", raising=False)
        assert Settings(_env_file=None).pod_hmac_key is None

    def test_empty_is_unset(self, monkeypatch):
        """An empty variable — a chart rendering an absent secret — is no key.

        @verifies REQ-0105
        """
        monkeypatch.setenv("POD_HMAC_KEY", "")
        assert Settings(_env_file=None).pod_hmac_key is None

    def test_it_is_read_from_the_environment(self, monkeypatch):
        """@verifies REQ-0105"""
        monkeypatch.setenv("POD_HMAC_KEY", KEY)
        assert Settings(_env_file=None).pod_hmac_key.get_secret_value() == KEY

    @pytest.mark.parametrize("short", ["x", "a" * 31, " " * 40])
    def test_a_short_key_refuses_to_start(self, monkeypatch, short):
        """@verifies REQ-0105"""
        monkeypatch.setenv("POD_HMAC_KEY", short)
        with pytest.raises(ValidationError) as exc:
            Settings(_env_file=None)
        assert short.strip() == "" or short not in str(exc.value)

    def test_thirty_two_characters_is_enough(self, monkeypatch):
        """@verifies REQ-0105"""
        monkeypatch.setenv("POD_HMAC_KEY", "b" * 32)
        assert Settings(_env_file=None).pod_hmac_key is not None

    def test_it_never_shows_in_a_repr_or_dump(self, monkeypatch):
        """@verifies REQ-0105"""
        monkeypatch.setenv("POD_HMAC_KEY", KEY)
        s = Settings(_env_file=None)
        assert KEY not in repr(s)
        assert KEY not in str(s.model_dump())
        assert KEY not in s.model_dump_json()


# =============================================================================
# Both exports, against the real schema
# =============================================================================

POD_1 = "IT001E00000001"
POD_2 = "IT001E00000002"
POD_3 = "IT001E00000003"  # an inactive delivery point of ex-00001
POD_4 = "IT001E00000004"  # a meter's pod no delivery point lists


def _keyed_bundle(key: str) -> dict:
    bundle = _bundle(key)
    one = bundle["members"]["ex-00001"]
    one["delivery_points"].append({"id": f" {POD_3.lower()} ", "type": "pod", "active": False})
    one["delivery_points"].append({"id": "ES0021000000000001AB", "type": "cups"})
    one["assets"]["meter"]["meter-ex-sensor-0003"] = {
        "name": "Meter without a pod", "meter_type": "production", "sensor_id": "ex-sensor-0003",
    }
    one["assets"]["meter"]["meter-ex-sensor-0004"] = {
        "name": "Meter on another pod", "meter_type": "production",
        "sensor_id": "ex-sensor-0004", "pod": POD_4,
    }
    return bundle


async def _seed(client, key: str = "export-rec") -> str:
    r = await client.post(
        "/admin/import", json={"bundle": _keyed_bundle(key), "dry_run": False}
    )
    assert r.status_code == 200, r.text
    return key


@pytest.fixture
def with_key(monkeypatch):
    from celine.rec_registry.core.settings import settings

    monkeypatch.setattr(settings, "pod_hmac_key", SecretStr(KEY))


@pytest.fixture
def without_key(monkeypatch):
    from celine.rec_registry.core.settings import settings

    monkeypatch.setattr(settings, "pod_hmac_key", None)


ROUTES = ["/admin/export/members", "/admin/export/mirror"]


@pytest.mark.integration
class TestTheExportsWithAKey:
    @pytest.mark.parametrize("route", ROUTES)
    async def test_each_member_carries_its_hashes(self, live_client, with_key, route):
        """@verifies REQ-0105"""
        await _seed(live_client)

        r = await live_client.get(route)

        assert r.status_code == 200, r.text
        one, two = r.json()["communities"][0]["members"]
        assert one["pod_hashes"] == sorted(
            [_expected(POD_1), _expected("ES0021000000000001AB")]
        )
        assert one["meter_pod_hashes"] == {
            "ex-sensor-0001": _expected(POD_1),
            "ex-sensor-0003": None,
            "ex-sensor-0004": _expected(POD_4),
        }
        # A suspended member's active points are its points all the same.
        assert two["pod_hashes"] == [_expected(POD_2)]
        assert two["meter_pod_hashes"] == {"ex-sensor-0002": _expected(POD_2)}

    @pytest.mark.parametrize("route", ROUTES)
    async def test_an_inactive_delivery_point_is_not_hashed(self, live_client, with_key, route):
        """@verifies REQ-0105"""
        await _seed(live_client)

        r = await live_client.get(route)

        assert _expected(POD_3) not in r.text

    @pytest.mark.parametrize("route", ROUTES)
    async def test_no_raw_pod_and_no_key_reaches_it(self, live_client, with_key, route):
        """@verifies REQ-0105"""
        await _seed(live_client)

        r = await live_client.get(route)

        assert r.status_code == 200, r.text
        text = r.text.lower()
        for raw in (POD_1, POD_2, POD_3, POD_4, "ES0021000000000001AB", KEY):
            assert raw.lower() not in text
        allowed = {"0b6f6c3e-8d2a-4c41-9f0e-5a7d2c1b9e10"} if route.endswith("mirror") else set()
        assert {v for v in PERSONAL if v in r.text} == allowed


@pytest.mark.integration
class TestTheExportsWithoutAKey:
    @pytest.mark.parametrize("route", ROUTES)
    async def test_the_fields_are_absent_not_empty(self, live_client, without_key, route):
        """@verifies REQ-0105"""
        await _seed(live_client)

        r = await live_client.get(route)

        assert r.status_code == 200, r.text
        for member in r.json()["communities"][0]["members"]:
            assert "pod_hashes" not in member
            assert "meter_pod_hashes" not in member
        for raw in (POD_1, POD_2, POD_3, POD_4):
            assert raw not in r.text
