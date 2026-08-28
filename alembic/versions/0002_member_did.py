"""
Add the dataspace DID to `member`.

The join key between the connector's answer to *who consents* — which is stated
in DIDs — and this registry's answer to *what they hold*. Nothing joined the two
before; resolving a DID through the identity registry to a Keycloak user id does
not work here, because `member.user_id` holds a Keycloak *username* and the
identifier that hop returns matches no row.

Nullable with no backfill, so this does nothing to a populated database beyond
adding an empty column: the DID is minted a step after the member is registered,
and a deployment with no dataspace never populates it.

The index is **global** rather than per-community, unlike the two uniqueness
rules `0001` created. At most one member per DID, any number without one —
Postgres treats NULLs as distinct, so the nullable column and the unique index
want each other rather than fight.

Revision ID: 0002_member_did
Revises: 0001_v04_schema
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_member_did"
down_revision = "0001_v04_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("member", sa.Column("did", sa.String(length=512), nullable=True))
    op.create_index("ix_member_did", "member", ["did"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_member_did", table_name="member")
    op.drop_column("member", "did")
