-- postmortem_reports DDL — shared/reports/models.py PostMortemReportTable와 1:1 (멱등)
-- PG13+ 내장 gen_random_uuid() 사용.
-- 이 파일 변경 시 kustomize configMapGenerator 해시가 바뀌어 init Job이 자동 재실행됨.
CREATE TABLE IF NOT EXISTS postmortem_reports (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id       VARCHAR(64) NOT NULL,
    contract_version  VARCHAR(16) NOT NULL,
    generated_at      TIMESTAMPTZ NOT NULL,
    severity          VARCHAR(16) NOT NULL,
    incident_summary  TEXT        NOT NULL,
    timeline          TEXT        NOT NULL DEFAULT '',
    root_cause        TEXT        NOT NULL DEFAULT '',
    impact            TEXT        NOT NULL DEFAULT '',
    action_items      TEXT[]      NOT NULL DEFAULT '{}',
    lessons_learned   TEXT        NOT NULL DEFAULT '',
    isolation_applied BOOLEAN     NOT NULL DEFAULT false,
    evidence          JSONB       NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_postmortem_reports_workflow_generated
    ON postmortem_reports (workflow_id, generated_at);
