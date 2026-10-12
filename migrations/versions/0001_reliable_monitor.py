"""Initial schema, including additive upgrade of the original portfolio database."""

from alembic import op
import sqlalchemy as sa

revision = "0001_reliable_monitor"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "demo_states" not in existing:
        op.create_table(
            "demo_states",
            sa.Column("owner", sa.String(40), primary_key=True, nullable=False),
            sa.Column("service", sa.String(20), primary_key=True, nullable=False),
            sa.Column("mode", sa.String(20), primary_key=False, nullable=False),
            sa.Column("delay_seconds", sa.Float(), primary_key=False, nullable=False),
            sa.Column(
                "expires_at",
                sa.DateTime(timezone=True),
                primary_key=False,
                nullable=False,
            ),
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("demo_states")}
    if "ix_demo_states_expires_at" not in indexes:
        op.create_index(
            "ix_demo_states_expires_at", "demo_states", ["expires_at"], unique=False
        )
    if "heartbeats" not in existing:
        op.create_table(
            "heartbeats",
            sa.Column("name", sa.String(120), primary_key=True, nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                primary_key=False,
                nullable=False,
            ),
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("heartbeats")}
    if "integrations" not in existing:
        op.create_table(
            "integrations",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("name", sa.String(120), primary_key=False, nullable=False),
            sa.Column("endpoint", sa.String(1000), primary_key=False, nullable=False),
            sa.Column("method", sa.String(10), primary_key=False, nullable=False),
            sa.Column(
                "expected_status", sa.Integer(), primary_key=False, nullable=False
            ),
            sa.Column("timeout_ms", sa.Integer(), primary_key=False, nullable=False),
            sa.Column(
                "latency_threshold_ms", sa.Integer(), primary_key=False, nullable=True
            ),
            sa.Column(
                "check_interval_seconds",
                sa.Integer(),
                primary_key=False,
                nullable=False,
            ),
            sa.Column(
                "expected_json_key", sa.String(255), primary_key=False, nullable=True
            ),
            sa.Column(
                "expected_json_value", sa.String(255), primary_key=False, nullable=True
            ),
            sa.Column("headers_json", sa.Text(), primary_key=False, nullable=True),
            sa.Column("active", sa.Boolean(), primary_key=False, nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                primary_key=False,
                nullable=False,
            ),
            sa.Column(
                "last_checked_at",
                sa.DateTime(timezone=True),
                primary_key=False,
                nullable=True,
            ),
            sa.Column("demo_owner", sa.String(40), primary_key=False, nullable=True),
            sa.Column("demo_key", sa.String(20), primary_key=False, nullable=True),
        )
    columns = {c["name"] for c in sa.inspect(bind).get_columns("integrations")}
    if "demo_owner" not in columns:
        op.add_column(
            "integrations", sa.Column("demo_owner", sa.String(40), nullable=True)
        )
    if "demo_key" not in columns:
        op.add_column(
            "integrations", sa.Column("demo_key", sa.String(20), nullable=True)
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("integrations")}
    if "ix_integrations_active" not in indexes:
        op.create_index(
            "ix_integrations_active", "integrations", ["active"], unique=False
        )
    if "ix_integrations_demo_owner" not in indexes:
        op.create_index(
            "ix_integrations_demo_owner", "integrations", ["demo_owner"], unique=False
        )
    if "ix_integrations_name" not in indexes:
        op.create_index("ix_integrations_name", "integrations", ["name"], unique=True)
    if "check_runs" not in existing:
        op.create_table(
            "check_runs",
            sa.Column("execution_id", sa.String(64), primary_key=True, nullable=False),
            sa.Column(
                "integration_id",
                sa.Integer(),
                sa.ForeignKey("integrations.id"),
                primary_key=False,
                nullable=False,
            ),
            sa.Column("status", sa.String(20), primary_key=False, nullable=False),
            sa.Column("attempts", sa.Integer(), primary_key=False, nullable=False),
            sa.Column(
                "scheduled_at",
                sa.DateTime(timezone=True),
                primary_key=False,
                nullable=False,
            ),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                primary_key=False,
                nullable=True,
            ),
            sa.Column(
                "finished_at",
                sa.DateTime(timezone=True),
                primary_key=False,
                nullable=True,
            ),
            sa.Column(
                "lease_until",
                sa.DateTime(timezone=True),
                primary_key=False,
                nullable=True,
            ),
            sa.Column("lease_token", sa.String(40), primary_key=False, nullable=True),
            sa.Column("error_code", sa.String(40), primary_key=False, nullable=True),
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("check_runs")}
    if "ix_check_runs_integration_id" not in indexes:
        op.create_index(
            "ix_check_runs_integration_id",
            "check_runs",
            ["integration_id"],
            unique=False,
        )
    if "ix_check_runs_status" not in indexes:
        op.create_index("ix_check_runs_status", "check_runs", ["status"], unique=False)
    if "uq_one_inflight_run" not in indexes:
        op.create_index(
            "uq_one_inflight_run",
            "check_runs",
            ["integration_id"],
            unique=True,
            sqlite_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
            postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
        )
    if "health_checks" not in existing:
        op.create_table(
            "health_checks",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("execution_id", sa.String(64), primary_key=False, nullable=False),
            sa.Column(
                "integration_id",
                sa.Integer(),
                sa.ForeignKey("integrations.id"),
                primary_key=False,
                nullable=False,
            ),
            sa.Column(
                "checked_at",
                sa.DateTime(timezone=True),
                primary_key=False,
                nullable=False,
            ),
            sa.Column("outcome", sa.String(20), primary_key=False, nullable=False),
            sa.Column("http_status", sa.Integer(), primary_key=False, nullable=True),
            sa.Column("latency_ms", sa.Float(), primary_key=False, nullable=True),
            sa.Column("failure_type", sa.String(40), primary_key=False, nullable=True),
            sa.Column("error_message", sa.Text(), primary_key=False, nullable=True),
            sa.UniqueConstraint("execution_id", name="uq_health_checks_execution_id"),
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("health_checks")}
    if "ix_checks_integration_time" not in indexes:
        op.create_index(
            "ix_checks_integration_time",
            "health_checks",
            ["integration_id", "checked_at", "id"],
            unique=False,
        )
    if "ix_health_checks_checked_at" not in indexes:
        op.create_index(
            "ix_health_checks_checked_at", "health_checks", ["checked_at"], unique=False
        )
    if "ix_health_checks_execution_id" not in indexes:
        op.create_index(
            "ix_health_checks_execution_id",
            "health_checks",
            ["execution_id"],
            unique=False,
        )
    if "ix_health_checks_failure_type" not in indexes:
        op.create_index(
            "ix_health_checks_failure_type",
            "health_checks",
            ["failure_type"],
            unique=False,
        )
    if "ix_health_checks_integration_id" not in indexes:
        op.create_index(
            "ix_health_checks_integration_id",
            "health_checks",
            ["integration_id"],
            unique=False,
        )
    if "ix_health_checks_outcome" not in indexes:
        op.create_index(
            "ix_health_checks_outcome", "health_checks", ["outcome"], unique=False
        )
    if "incidents" not in existing:
        op.create_table(
            "incidents",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column(
                "integration_id",
                sa.Integer(),
                sa.ForeignKey("integrations.id"),
                primary_key=False,
                nullable=False,
            ),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                primary_key=False,
                nullable=False,
            ),
            sa.Column(
                "resolved_at",
                sa.DateTime(timezone=True),
                primary_key=False,
                nullable=True,
            ),
            sa.Column("status", sa.String(20), primary_key=False, nullable=False),
            sa.Column("severity", sa.String(20), primary_key=False, nullable=False),
            sa.Column("cause", sa.String(40), primary_key=False, nullable=True),
            sa.Column("failure_count", sa.Integer(), primary_key=False, nullable=False),
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("incidents")}
    if "ix_incidents_integration_id" not in indexes:
        op.create_index(
            "ix_incidents_integration_id", "incidents", ["integration_id"], unique=False
        )
    if "ix_incidents_started_at" not in indexes:
        op.create_index(
            "ix_incidents_started_at", "incidents", ["started_at"], unique=False
        )
    if "ix_incidents_status" not in indexes:
        op.create_index("ix_incidents_status", "incidents", ["status"], unique=False)
    if "uq_one_open_incident" not in indexes:
        op.create_index(
            "uq_one_open_incident",
            "incidents",
            ["integration_id"],
            unique=True,
            sqlite_where=sa.text("status = 'OPEN'"),
            postgresql_where=sa.text("status = 'OPEN'"),
        )
    if "alert_events" not in existing:
        op.create_table(
            "alert_events",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column(
                "incident_id",
                sa.Integer(),
                sa.ForeignKey("incidents.id"),
                primary_key=False,
                nullable=False,
            ),
            sa.Column("channel", sa.String(30), primary_key=False, nullable=False),
            sa.Column("event_type", sa.String(30), primary_key=False, nullable=False),
            sa.Column(
                "sent_at", sa.DateTime(timezone=True), primary_key=False, nullable=False
            ),
            sa.Column("status", sa.String(20), primary_key=False, nullable=False),
            sa.Column("error_message", sa.Text(), primary_key=False, nullable=True),
            sa.Column("payload_json", sa.Text(), primary_key=False, nullable=True),
            sa.Column("attempts", sa.Integer(), primary_key=False, nullable=False),
            sa.Column(
                "next_attempt_at",
                sa.DateTime(timezone=True),
                primary_key=False,
                nullable=False,
            ),
            sa.Column(
                "lease_until",
                sa.DateTime(timezone=True),
                primary_key=False,
                nullable=True,
            ),
            sa.Column("lease_token", sa.String(40), primary_key=False, nullable=True),
            sa.UniqueConstraint(
                "incident_id", "event_type", name="uq_alert_transition"
            ),
        )
    columns = {c["name"] for c in sa.inspect(bind).get_columns("alert_events")}
    if "payload_json" not in columns:
        op.add_column(
            "alert_events", sa.Column("payload_json", sa.Text(), nullable=True)
        )
    if "attempts" not in columns:
        op.add_column(
            "alert_events",
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        )
    if "next_attempt_at" not in columns:
        op.add_column(
            "alert_events",
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "lease_until" not in columns:
        op.add_column(
            "alert_events",
            sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        )
    if "lease_token" not in columns:
        op.add_column(
            "alert_events", sa.Column("lease_token", sa.String(40), nullable=True)
        )
    bind.execute(
        sa.text(
            "UPDATE alert_events SET next_attempt_at = CURRENT_TIMESTAMP WHERE next_attempt_at IS NULL"
        )
    )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("alert_events")}
    if "ix_alert_events_incident_id" not in indexes:
        op.create_index(
            "ix_alert_events_incident_id", "alert_events", ["incident_id"], unique=False
        )
    if "ix_alert_events_status" not in indexes:
        op.create_index(
            "ix_alert_events_status", "alert_events", ["status"], unique=False
        )
    uniques = {
        c["name"] for c in sa.inspect(bind).get_unique_constraints("alert_events")
    }
    if "uq_alert_transition" not in uniques and "uq_alert_transition" not in indexes:
        op.create_index(
            "uq_alert_transition",
            "alert_events",
            ["incident_id", "event_type"],
            unique=True,
        )


def downgrade():
    raise RuntimeError(
        "Use a database backup to restore the legacy schema; destructive downgrade is intentionally unsupported."
    )
