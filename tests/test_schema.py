"""
Schema validation tests — parse rec-example.yaml and assert shape correctness.
"""

import pytest
from pydantic import ValidationError

from celine.rec_registry.core.versions import CURRENT_SCHEMA_VERSION
from celine.rec_registry.schemas.bundle import MemberIn, RegistryBundleIn
from celine.rec_registry.services.importer import schema_version_warnings


class TestBundleParsing:
    def test_parses_without_error(self, example_bundle):
        """@verifies REQ-0011"""
        assert example_bundle is not None

    def test_schema_version(self, example_bundle):
        """@verifies REQ-0018"""
        assert example_bundle.schema_version == "0.5"

    def test_community_id(self, example_bundle):
        """@verifies REQ-0011"""
        assert example_bundle.community.id == "example_rec"

    def test_community_has_three_areas(self, example_bundle):
        """@verifies REQ-0011"""
        areas = example_bundle.community.areas
        assert set(areas.keys()) == {"northern", "southern"}

    def test_area_topology(self, example_bundle):
        """@verifies REQ-0011"""
        northern = example_bundle.community.areas["northern"]
        assert northern.topology == ["AC001E00001"]

    def test_community_topology_nodes(self, example_bundle):
        """@verifies REQ-0011"""
        topology = example_bundle.community.topology
        assert len(topology) == 3
        types = {n.type for n in topology}
        assert "primary_substation" in types
        assert "secondary_substation" in types

    def test_community_operator(self, example_bundle):
        """@verifies REQ-0011"""
        operators = example_bundle.community.operators
        assert "example_dso" in operators
        assert operators["example_dso"].name == "Example Distribution Network Operator"

    def test_member_count(self, example_bundle):
        """@verifies REQ-0012"""
        assert len(example_bundle.members) == 4

    def test_member_required_fields(self, example_bundle):
        """@verifies REQ-0012"""
        m = example_bundle.members["ah-00001"]
        assert m.user_id == "ah-00001"
        assert m.role == "consumer"
        assert m.area == "northern"
        assert m.status == "active"

    def test_member_type_person(self, example_bundle):
        """@verifies REQ-0013"""
        assert example_bundle.members["ah-00001"].type == "schema:Person"

    def test_member_type_government(self, example_bundle):
        """@verifies REQ-0013"""
        assert example_bundle.members["ah-00003"].type == "schema:GovernmentOrganization"

    def test_member_type_local_business(self, example_bundle):
        """@verifies REQ-0013"""
        assert example_bundle.members["ah-00004"].type == "schema:LocalBusiness"

    def test_member_with_pv_and_meter(self, example_bundle):
        """@verifies REQ-0014"""
        m = example_bundle.members["ah-00002"]
        assert "pv-ah-00002" in m.assets.pv
        assert "meter-ah-00002" in m.assets.meter

    def test_member_with_storage(self, example_bundle):
        """@verifies REQ-0014"""
        m = example_bundle.members["ah-00003"]
        assert "storage-ah-00003" in m.assets.storage

    def test_meter_sensor_id(self, example_bundle):
        """@verifies REQ-0015"""
        meter = example_bundle.members["ah-00001"].assets.meter["meter-ah-00001"]
        assert meter.sensor_id == "c2g-F00000001"
        assert meter.meter_type == "consumption"

    def test_meter_pod_reference(self, example_bundle):
        """@verifies REQ-0015"""
        meter = example_bundle.members["ah-00001"].assets.meter["meter-ah-00001"]
        assert meter.pod == "POD-8KQ2M7T1V6ZN"

    def test_pv_relationships(self, example_bundle):
        """@verifies REQ-0016"""
        pv = example_bundle.members["ah-00002"].assets.pv["pv-ah-00002"]
        assert "meter-ah-00002" in pv.relationships.measures

    def test_delivery_point(self, example_bundle):
        """@verifies REQ-0017"""
        m = example_bundle.members["ah-00001"]
        assert len(m.delivery_points) == 1
        dp = m.delivery_points[0]
        assert dp.type == "pod"
        assert dp.active is True


class TestTheSchemaVersionIsReadAndReported:
    """`schema_version` is read, reported, and never a reason to refuse.

    It used to be read by nothing, which is exactly why four places held three
    opinions about its value: a field nobody reads has nothing holding its
    copies to each other. Now one module says what the current version is and
    everything else asks it.

    What deliberately did **not** change: no value is refused. An older,
    unrecognised or absent version still imports and the caller is told, because
    refusing breaks restoring a backup — and a backup is restored when something
    has already gone wrong. This is a report, not a compatibility gate, and the
    tests below say so in both directions.
    """

    def test_any_value_at_all_is_still_accepted(self):
        """A v0.4 bundle, a v0.5 bundle and a nonsense one all still parse.

        @verifies REQ-0018
        """
        for declared in ("0.4", "0.5", "1.0", "not-a-version"):
            bundle = RegistryBundleIn(
                **{
                    "schema_version": declared,
                    "community": {"id": "v", "name": "V", "areas": {}},
                    "members": {},
                }
            )
            assert bundle.schema_version == declared

    def test_an_absent_version_defaults_to_the_current_one(self):
        """It defaulted to `1.0`, which named no schema that has ever existed.

        @verifies REQ-0018
        """
        bundle = RegistryBundleIn(
            **{"community": {"id": "v", "name": "V", "areas": {}}, "members": {}}
        )

        assert bundle.schema_version == CURRENT_SCHEMA_VERSION

    def test_the_example_bundle_declares_what_an_export_would_emit(
        self, example_bundle
    ):
        """The example said `0.5` and an export said `1.0`, so a round trip did
        not preserve the one field whose job is to describe the shape of the
        rest. Both now read the same constant.

        @verifies REQ-0018
        """
        assert example_bundle.schema_version == CURRENT_SCHEMA_VERSION
        assert (
            RegistryBundleIn.model_fields["schema_version"].default
            == CURRENT_SCHEMA_VERSION
        )

    def test_the_current_version_is_silent(self):
        """@verifies REQ-0018"""
        bundle = RegistryBundleIn(
            **{
                "schema_version": CURRENT_SCHEMA_VERSION,
                "community": {"id": "v", "name": "V", "areas": {}},
                "members": {},
            }
        )

        assert schema_version_warnings(bundle) == []

    def test_an_older_published_version_is_warned_about_not_refused(self):
        """`0.4` is a real schema in `schemas/community/`, and v0.5 removed
        fields from it. Importing one is a thing somebody may have to do; doing
        it without being told is not.

        @verifies REQ-0018
        """
        bundle = RegistryBundleIn(
            **{
                "schema_version": "0.4",
                "community": {"id": "v", "name": "V", "areas": {}},
                "members": {},
            }
        )

        (warning,) = schema_version_warnings(bundle)
        assert "0.4" in warning
        assert CURRENT_SCHEMA_VERSION in warning

    def test_an_unpublished_version_is_warned_about_not_refused(self):
        """@verifies REQ-0018"""
        bundle = RegistryBundleIn(
            **{
                "schema_version": "not-a-version",
                "community": {"id": "v", "name": "V", "areas": {}},
                "members": {},
            }
        )

        (warning,) = schema_version_warnings(bundle)
        assert "not-a-version" in warning

    def test_an_absent_version_is_warned_about_rather_than_assumed_silently(self):
        """The default is a reading, not a declaration, and the two are worth
        telling apart: a file that does not say which schema it follows is a
        file nobody checked.

        @verifies REQ-0018
        """
        bundle = RegistryBundleIn(
            **{"community": {"id": "v", "name": "V", "areas": {}}, "members": {}}
        )

        (warning,) = schema_version_warnings(bundle)
        assert "no schema_version" in warning


class TestBundleValidation:
    def test_missing_community_raises(self):
        """@verifies REQ-0019"""
        with pytest.raises(ValidationError):
            RegistryBundleIn(schema_version="0.5")  # type: ignore[call-arg]

    def test_member_missing_role_raises(self):
        """@verifies REQ-0019"""
        with pytest.raises(ValidationError):
            MemberIn(user_id="x", name="y", area="z", status="active")  # type: ignore[call-arg]

    def test_member_missing_area_raises(self):
        """@verifies REQ-0019"""
        with pytest.raises(ValidationError):
            MemberIn(user_id="x", name="y", role="consumer", status="active")  # type: ignore[call-arg]
