"""
Hold `member.did` unique among **active** members only.

`0002` made the DID unique across every row. Release leaves a member's row in
place as `inactive`, DID included, so that row blocked the DID from being held
by an active member anywhere again — a person released by one community could
not be registered under the same DID by another (REQ-0096).

The index keeps its name, so the conflict translation that matches on it
(`services/members.py::member_conflict_from`) is unchanged, and keeps its
column; only the `WHERE status = 'active'` is new. Every row the old index
accepted, the new one accepts too, so `upgrade` cannot fail on existing data.

`downgrade` can: once two rows share a DID — an inactive one and an active one,
which is exactly what this revision permits — the global index cannot be built.
It fails rather than guessing which row to clear; clear the inactive row's
`did` first if a downgrade is really wanted.

Revision ID: 0003_member_did_active_only
Revises: 0002_member_did
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_member_did_active_only"
down_revision = "0002_member_did"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_member_did", table_name="member")
    op.create_index(
        "ix_member_did",
        "member",
        ["did"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("ix_member_did", table_name="member")
    op.create_index("ix_member_did", "member", ["did"], unique=True)
