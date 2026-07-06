# Cluster State Agent

## 역할

실제 Kubernetes 클러스터의 전체 Deployment와 HPA 상태를 읽고, 이벤트와 직접 관련 없는 유휴 자원 후보를 찾습니다. EC2 Spot 가격을 참고해 이벤트 기간 동안 절감 가능한 비용을 추정합니다.

## 읽어오는 데이터

- 전체 Deployment 목록
- 전체 HPA 설정과 현재 replica 수
- EC2 Spot 인스턴스 가격

## 반환 가능한 필드

- `total_cluster_pods`
- `total_event_related_pods`
- `idle_candidates`
- `idle_candidate_count`
- `total_reducible_pods`
- `total_estimated_saving_usd`
- `spot_price_m5xlarge`

## 처리하지 않는 요청

- 실제 Pod 삭제 또는 축소 실행
- CloudWatch 지표 직접 조회
- 실제 HPA/Deployment 설정 변경
