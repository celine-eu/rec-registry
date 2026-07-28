"""
Schema validation tests — parse rec-example.yaml and assert shape correctness.
"""

import pytest
from pydantic import ValidationError

from celine.rec_registry.schemas.bundle import MemberIn, RegistryBundleIn


class TestBundleParsing:
    def test_parses_without_error(self, example_bundle):
        assert example_bundle is not None

    def test_schema_version(self, example_bundle):
        assert example_bundle.schema_version == "0.5"

    def test_community_id(self, example_bundle):
        assert example_bundle.community.id == "example_rec"

    def test_community_has_three_areas(self, example_bundle):
        areas = example_bundle.community.areas
        assert set(areas.keys()) == {"northern", "southern"}

    def test_area_topology(self, example_bundle):
        northern = example_bundle.community.areas["northern"]
        assert northern.topology == ["AC001E00001"]

    def test_community_topology_nodes(self, example_bundle):
        topology = example_bundle.community.topology
        assert len(topology) == 3
        types = {n.type for n in topology}
        assert "primary_substation" in types
        assert "secondary_substation" in types

    def test_community_operator(self, example_bundle):
        operators = example_bundle.community.operators
        assert "example_dso" in operators
        assert operators["example_dso"].name == "Example Distribution Network Operator"

    def test_member_count(self, example_bundle):
        assert len(example_bundle.members) == 4

    def test_member_required_fields(self, example_bundle):
        m = example_bundle.members["ah-00001"]
        assert m.user_id == "ah-00001"
        assert m.role == "consumer"
        assert m.area == "northern"
        assert m.status == "active"

    def test_member_type_person(self, example_bundle):
        assert example_bundle.members["ah-00001"].type == "schema:Person"

    def test_member_type_government(self, example_bundle):
        assert example_bundle.members["ah-00003"].type == "schema:GovernmentOrganization"

    def test_member_type_local_business(self, example_bundle):
        assert example_bundle.members["ah-00004"].type == "schema:LocalBusiness"

    def test_member_with_pv_and_meter(self, example_bundle):
        m = example_bundle.members["ah-00002"]
        assert "pv-ah-00002" in m.assets.pv
        assert "meter-ah-00002" in m.assets.meter

    def test_member_with_storage(self, example_bundle):
        m = example_bundle.members["ah-00003"]
        assert "storage-ah-00003" in m.assets.storage

    def test_meter_sensor_id(self, example_bundle):
        meter = example_bundle.members["ah-00001"].assets.meter["meter-ah-00001"]
        assert meter.sensor_id == "c2g-F00000001"
        assert meter.meter_type == "consumption"

    def test_meter_pod_reference(self, example_bundle):
        meter = example_bundle.members["ah-00001"].assets.meter["meter-ah-00001"]
        assert meter.pod == "POD-8KQ2M7T1V6ZN"

    def test_pv_relationships(self, example_bundle):
        pv = example_bundle.members["ah-00002"].assets.pv["pv-ah-00002"]
        assert "meter-ah-00002" in pv.relationships.measures

    def test_delivery_point(self, example_bundle):
        m = example_bundle.members["ah-00001"]
        assert len(m.delivery_points) == 1
        dp = m.delivery_points[0]
        assert dp.type == "pod"
        assert dp.active is True


class TestBundleValidation:
    def test_missing_community_raises(self):
        with pytest.raises(ValidationError):
            RegistryBundleIn(schema_version="0.5")  # type: ignore[call-arg]

    def test_member_missing_role_raises(self):
        with pytest.raises(ValidationError):
            MemberIn(user_id="x", name="y", area="z", status="active")  # type: ignore[call-arg]

    def test_member_missing_area_raises(self):
        with pytest.raises(ValidationError):
            MemberIn(user_id="x", name="y", role="consumer", status="active")  # type: ignore[call-arg]
