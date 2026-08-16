"""
Unit tests for the importer service.

Uses mocked AsyncSession — no real database required.
"""

import pytest
from unittest.mock import MagicMock

from celine.rec_registry.schemas.bundle import RegistryBundleIn
from celine.rec_registry.services.importer import (
    ImportWouldOverwrite,
    replacement_import_bundle,
)


@pytest.fixture
def minimal_bundle() -> RegistryBundleIn:
    """Smallest valid bundle with one member carrying one meter."""
    return RegistryBundleIn(
        **{
            "version": "1.0",
            "schema_version": "0.5",
            "community": {
                "id": "test-rec",
                "name": "Test REC",
                "areas": {},
                "topology": [],
            },
            "members": {
                "m-001": {
                    "user_id": "m-001",
                    "name": "Member One",
                    "role": "consumer",
                    "area": "north",
                    "status": "active",
                    "assets": {
                        "meter": {
                            "meter-m-001": {
                                "name": "Meter 1",
                                "sensor_id": "c2g-AABBCC001",
                                "meter_type": "consumption",
                            }
                        }
                    },
                }
            },
        }
    )


class TestDryRun:
    async def test_no_existing_community_returns_zero_deleted(
        self, mock_session, minimal_bundle
    ):
        """@verifies REQ-0034"""
        mock_session.scalar.return_value = None

        key, deleted, inserted, warnings = await replacement_import_bundle(
            mock_session, minimal_bundle, dry_run=True
        )

        assert key == "test-rec"
        assert deleted == {"community": 0, "member": 0, "asset": 0}
        assert inserted["community"] == 1
        assert inserted["member"] == 1
        assert inserted["asset"] == 1
        assert warnings == []

    async def test_existing_community_counts_deletions(
        self, mock_session, minimal_bundle
    ):
        """@verifies REQ-0034"""
        existing = MagicMock()
        existing.members = [MagicMock()] * 3
        existing.assets = [MagicMock()] * 7
        mock_session.scalar.return_value = existing

        key, deleted, inserted, warnings = await replacement_import_bundle(
            mock_session, minimal_bundle, dry_run=True
        )

        assert deleted == {"community": 1, "member": 3, "asset": 7}
        mock_session.delete.assert_not_called()

    async def test_dry_run_does_not_call_add(self, mock_session, minimal_bundle):
        """@verifies REQ-0034"""
        mock_session.scalar.return_value = None

        await replacement_import_bundle(mock_session, minimal_bundle, dry_run=True)

        mock_session.add.assert_not_called()


class TestLiveImport:
    async def test_new_import_adds_community_and_members(
        self, mock_session, example_bundle
    ):
        """@verifies REQ-0032"""
        mock_session.scalar.return_value = None

        key, deleted, inserted, warnings = await replacement_import_bundle(
            mock_session, example_bundle, dry_run=False
        )

        assert key == "example_rec"
        assert inserted["community"] == 1
        assert inserted["member"] == 4
        # community + 4 members + 7 assets, all added via session.add
        assert mock_session.add.call_count >= 5

    async def test_replacement_deletes_existing_before_insert(
        self, mock_session, minimal_bundle
    ):
        """@verifies REQ-0032"""
        existing = MagicMock()
        existing.members = []
        existing.assets = []
        mock_session.scalar.return_value = existing

        await replacement_import_bundle(
            mock_session, minimal_bundle, dry_run=False, force=True
        )

        mock_session.delete.assert_awaited_once_with(existing)

    async def test_replacing_an_existing_community_needs_force(
        self, mock_session, minimal_bundle
    ):
        """Members now arrive at runtime, so a stale export is the likeliest way
        to lose them. Overwriting has to be asked for.

        @verifies REQ-0033
        """
        existing = MagicMock()
        existing.members = [MagicMock(), MagicMock()]
        existing.assets = [MagicMock()]
        mock_session.scalar.return_value = existing

        with pytest.raises(ImportWouldOverwrite) as exc:
            await replacement_import_bundle(mock_session, minimal_bundle, dry_run=False)

        # The refusal names what would have gone, so the caller can judge.
        assert exc.value.members == 2
        assert exc.value.assets == 1
        mock_session.delete.assert_not_awaited()

    async def test_dry_run_reports_instead_of_refusing(
        self, mock_session, minimal_bundle
    ):
        """Seeing the counts is how a caller decides whether force is warranted,
        so a dry run must not be blocked by the guard it informs.

        @verifies REQ-0034
        """
        existing = MagicMock()
        existing.members = [MagicMock()]
        existing.assets = []
        mock_session.scalar.return_value = existing

        _, deleted, _, _ = await replacement_import_bundle(
            mock_session, minimal_bundle, dry_run=True
        )

        assert deleted["member"] == 1
        mock_session.delete.assert_not_awaited()

    async def test_a_new_community_needs_no_force(self, mock_session, minimal_bundle):
        """@verifies REQ-0033"""
        mock_session.scalar.return_value = None

        key, deleted, _, _ = await replacement_import_bundle(
            mock_session, minimal_bundle, dry_run=False
        )

        assert deleted["community"] == 0

    async def test_flush_called_after_each_batch(self, mock_session, minimal_bundle):
        """@verifies REQ-0032"""
        mock_session.scalar.return_value = None

        await replacement_import_bundle(mock_session, minimal_bundle, dry_run=False)

        # At minimum: after community insert, after members, after assets
        assert mock_session.flush.await_count >= 3


class TestWarnings:
    async def test_meter_missing_sensor_id_is_skipped_with_warning(
        self, mock_session
    ):
        """@verifies REQ-0035"""
        bundle = RegistryBundleIn(
            **{
                "version": "1.0",
                "schema_version": "0.5",
                "community": {
                    "id": "warn-rec",
                    "name": "Warn REC",
                    "areas": {},
                    "topology": [],
                },
                "members": {
                    "m-bad": {
                        "user_id": "m-bad",
                        "name": "Bad Meter Member",
                        "role": "consumer",
                        "area": "north",
                        "status": "active",
                        "assets": {
                            "meter": {
                                "meter-bad": {
                                    "name": "No Sensor Meter",
                                    "sensor_id": "",
                                    "meter_type": "consumption",
                                }
                            }
                        },
                    }
                },
            }
        )
        mock_session.scalar.return_value = None

        _, _, _, warnings = await replacement_import_bundle(
            mock_session, bundle, dry_run=False
        )

        assert len(warnings) == 1
        assert "sensor_id" in warnings[0]
        assert "meter-bad" in warnings[0]

    async def test_valid_meter_produces_no_warnings(self, mock_session, minimal_bundle):
        """@verifies REQ-0035"""
        mock_session.scalar.return_value = None

        _, _, _, warnings = await replacement_import_bundle(
            mock_session, minimal_bundle, dry_run=False
        )

        assert warnings == []
