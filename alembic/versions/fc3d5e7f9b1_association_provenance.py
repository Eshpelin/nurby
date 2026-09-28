"""Mark association provenance without fabricating historical episodes."""

import sqlalchemy as sa
from alembic import op


revision = "fc3d5e7f9b1"
down_revision = "fb2c4d6e8a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("entity_associations", sa.Column("provenance", sa.JSON(), nullable=True))
    op.execute(
        """
        UPDATE entity_associations
        SET provenance = '{
          "kind": "legacy_aggregate",
          "version": 1,
          "individual_evidence_available": false,
          "reason": "association existed before the evidence ledger"
        }'
        WHERE provenance IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("entity_associations", "provenance")

