-- shared/audit/models.py 의 AuditLogTable 과 1:1. (RDS 배포 시엔 동일 DDL을 마이그레이션으로)
-- postgres:16 은 gen_random_uuid() 내장(PG13+) → 별도 extension 불필요.
CREATE TABLE IF NOT EXISTS audit_logs (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id      VARCHAR(64)  NOT NULL,
    contract_version VARCHAR(16)  NOT NULL,
    scenario         VARCHAR(32)  NOT NULL,
    event_type       VARCHAR(64)  NOT NULL,
    occurred_at      TIMESTAMPTZ  NOT NULL,
    actor            VARCHAR(128) NOT NULL,
    summary          TEXT         NOT NULL,
    payload          JSONB        NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_workflow_occurred
    ON audit_logs (workflow_id, occurred_at);
