-- compliance_reports DDL — shared/reports/models.py ComplianceReportTable와 1:1 (멱등)
-- PG13+ 내장 gen_random_uuid() 사용.
-- 이 파일 변경 시 kustomize configMapGenerator 해시가 바뀌어 init Job이 자동 재실행됨.
CREATE TABLE IF NOT EXISTS compliance_reports (
    id                   UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id          VARCHAR(64)      NOT NULL,
    contract_version     VARCHAR(16)      NOT NULL,
    generated_at         TIMESTAMPTZ      NOT NULL,
    severity             VARCHAR(16)      NOT NULL,
    violated_regulations TEXT[]           NOT NULL,
    threat_summary       TEXT             NOT NULL,
    action_taken         TEXT             NOT NULL,
    isolation_applied    BOOLEAN          NOT NULL,
    confidence           DOUBLE PRECISION NOT NULL,
    evidence             JSONB            NOT NULL,
    blast_radius_safe    BOOLEAN          NOT NULL DEFAULT false,
    blast_radius_detail  TEXT             NOT NULL DEFAULT ''
);
-- 기존 배포 테이블(재구축으로 이미 생성됨) 대응: 멱등 컬럼 추가
ALTER TABLE compliance_reports ADD COLUMN IF NOT EXISTS blast_radius_safe   BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE compliance_reports ADD COLUMN IF NOT EXISTS blast_radius_detail TEXT    NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_compliance_reports_workflow_generated
    ON compliance_reports (workflow_id, generated_at);
