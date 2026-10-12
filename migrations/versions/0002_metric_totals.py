from alembic import op
import sqlalchemy as sa

revision = "0002_metric_totals"
down_revision = "0001_reliable_monitor"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "metric_totals",
        sa.Column("key", sa.String(120), primary_key=True),
        sa.Column("value", sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table("metric_totals")
