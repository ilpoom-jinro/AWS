## 변경 요약
<!-- 무엇을, 왜 변경했는지 -->

## 관련 이슈
<!-- #52, #59 등 -->
- 

## 변경 유형
- [ ] 인프라 (Terraform)
- [ ] 애플리케이션 / 매니페스트 (gitops)
- [ ] CI/CD (workflow, buildspec)
- [ ] 문서
- [ ] 기타

## 변경 내용
- 

## 테스트 / 검증
- 

## 보안 체크리스트 (자동 스캔이 못 잡는 항목 — 리뷰어 육안 확인)
- [ ] IAM 권한 변경 시 최소권한 확인 (Action/Resource 와일드카드 `*` 없음, 사유 명시)
- [ ] 보안그룹/NACL 변경 시 0.0.0.0/0 없음 (있으면 사유 명시)
- [ ] 퍼블릭 노출 없음 (S3 public, RDS publicly_accessible, 의도치 않은 IGW/공인 IP)
- [ ] 신규 egress/외부 통신 추가 시 망분리 영향 검토 (VPC Endpoint 경유 확인)
- [ ] KMS 암호화 적용 확인 (신규 S3 / EBS / RDS / Secrets)
- [ ] 신규 네임스페이스 시 체크리스트 반영 (AppProject / Kyverno PSS 예외 / Pod Identity)
- [ ] 로깅 비활성화 없음 (CloudTrail / VPC Flow Logs / EKS Audit Logs)