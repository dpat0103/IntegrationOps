from alembic import op
import sqlalchemy as sa

revision = "0003_demo_limits"
down_revision = "0002_metric_totals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rate_limit_buckets",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_rate_limit_buckets_expires_at", "rate_limit_buckets", ["expires_at"]
    )


def downgrade():
    op.drop_table("rate_limit_buckets")
