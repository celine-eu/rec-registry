"""
Add the account subject to `member`.

The Keycloak `sub` of the account the member signs in with — the account's own
id, a UUID — beside `user_id`, which holds that account's *username* and stays
the value every lookup resolves by (REQ-0053). The subject is what the member
mirrors of the intermediate environments create their accounts under, so a
mirrored account keeps prod's id (REQ-0101).

Nullable with no backfill and no index: a member can exist before its account,
nothing looks a member up by it, and the rows already here are filled by
`celine-rec-registry backfill-subjects`, which reads Keycloak (REQ-0102). So
`upgrade` only adds an empty column to a populated database.

`downgrade` drops the column and what it held; the backfill can write it again.

Revision ID: 0004_member_subject
Revises: 0003_member_did_active_only
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_member_subject"
down_revision = "0003_member_did_active_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("member", sa.Column("subject", sa.String(length=36), nullable=True))


def downgrade() -> None:
    op.drop_column("member", "subject")
