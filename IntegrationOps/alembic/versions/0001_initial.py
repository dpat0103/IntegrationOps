"""Initial IntegrationOps schema."""
from alembic import op
import sqlalchemy as sa
revision='0001_initial'; down_revision=None; branch_labels=None; depends_on=None

def upgrade():
    op.create_table('integrations',
      sa.Column('id',sa.Integer(),primary_key=True), sa.Column('name',sa.String(120),nullable=False), sa.Column('endpoint',sa.String(1000),nullable=False),
      sa.Column('method',sa.String(10),nullable=False), sa.Column('expected_status',sa.Integer(),nullable=False), sa.Column('timeout_ms',sa.Integer(),nullable=False),
      sa.Column('latency_threshold_ms',sa.Integer(),nullable=True), sa.Column('availability_target_pct',sa.Float(),nullable=True), sa.Column('p95_latency_target_ms',sa.Integer(),nullable=True),
      sa.Column('check_interval_seconds',sa.Integer(),nullable=False), sa.Column('expected_json_key',sa.String(255),nullable=True), sa.Column('expected_json_value',sa.String(255),nullable=True),
      sa.Column('headers_json',sa.Text(),nullable=True), sa.Column('active',sa.Boolean(),nullable=False), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False), sa.Column('last_checked_at',sa.DateTime(timezone=True),nullable=True),
      sa.UniqueConstraint('name'))
    op.create_index('ix_integrations_name','integrations',['name']); op.create_index('ix_integrations_active','integrations',['active'])
    op.create_table('health_checks',
      sa.Column('id',sa.Integer(),primary_key=True), sa.Column('execution_id',sa.String(64),nullable=False), sa.Column('integration_id',sa.Integer(),sa.ForeignKey('integrations.id'),nullable=False),
      sa.Column('checked_at',sa.DateTime(timezone=True),nullable=False), sa.Column('outcome',sa.String(20),nullable=False), sa.Column('http_status',sa.Integer(),nullable=True),
      sa.Column('latency_ms',sa.Float(),nullable=True), sa.Column('failure_type',sa.String(40),nullable=True), sa.Column('error_message',sa.Text(),nullable=True),
      sa.Column('retry_after_seconds',sa.Integer(),nullable=True), sa.Column('response_content_type',sa.String(120),nullable=True), sa.Column('response_size_bytes',sa.Integer(),nullable=True),
      sa.UniqueConstraint('execution_id',name='uq_health_checks_execution_id'))
    for name,col in [('ix_health_checks_execution_id','execution_id'),('ix_health_checks_integration_id','integration_id'),('ix_health_checks_checked_at','checked_at'),('ix_health_checks_outcome','outcome'),('ix_health_checks_failure_type','failure_type')]: op.create_index(name,'health_checks',[col])
    op.create_table('incidents',
      sa.Column('id',sa.Integer(),primary_key=True), sa.Column('integration_id',sa.Integer(),sa.ForeignKey('integrations.id'),nullable=False), sa.Column('started_at',sa.DateTime(timezone=True),nullable=False),
      sa.Column('resolved_at',sa.DateTime(timezone=True),nullable=True), sa.Column('status',sa.String(20),nullable=False), sa.Column('severity',sa.String(20),nullable=False), sa.Column('cause',sa.String(40),nullable=True), sa.Column('failure_count',sa.Integer(),nullable=False))
    for name,col in [('ix_incidents_integration_id','integration_id'),('ix_incidents_started_at','started_at'),('ix_incidents_status','status')]: op.create_index(name,'incidents',[col])
    op.create_table('alert_events',
      sa.Column('id',sa.Integer(),primary_key=True), sa.Column('incident_id',sa.Integer(),sa.ForeignKey('incidents.id'),nullable=False), sa.Column('channel',sa.String(30),nullable=False),
      sa.Column('event_type',sa.String(30),nullable=False), sa.Column('sent_at',sa.DateTime(timezone=True),nullable=False), sa.Column('status',sa.String(20),nullable=False), sa.Column('error_message',sa.Text(),nullable=True))
    op.create_index('ix_alert_events_incident_id','alert_events',['incident_id'])

def downgrade():
    op.drop_table('alert_events'); op.drop_table('incidents'); op.drop_table('health_checks'); op.drop_table('integrations')
