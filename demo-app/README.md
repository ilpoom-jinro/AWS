# Stock Recommendation Demo App

간단한 인기 주식 추천 데모 서비스입니다.

구성은 다음과 같습니다.

- `frontend`: React + Vite 웹 화면
- `backend`: FastAPI 추천 종목 API
- `db`: PostgreSQL 초기 테이블 및 샘플 데이터
- `k8s`: Kubernetes 배포 예시 매니페스트

## Local Run

```bash
docker compose up --build
```

실행 후 브라우저에서 접속합니다.

```text
http://localhost:5173
```

API 헬스 체크:

```text
http://localhost:8000/health
```

추천 종목 API:

```text
http://localhost:8000/api/recommendations
```

## Demo Architecture

```text
User
  -> Web Server / Public Subnet
  -> Backend Server / Internal Private Subnet
  -> PostgreSQL / Public VPC Private DB Subnet
```

데모에서는 `docker-compose.yml`로 세 서비스를 한 번에 실행합니다.
운영 또는 클러스터 환경에서는 PostgreSQL 컨테이너 대신 RDS PostgreSQL을 사용하는 구성이 더 적합합니다.

## Kubernetes 배포 예시

이미지를 빌드하고 레지스트리에 푸시한 뒤 `k8s/*.yaml`의 이미지 이름을 수정합니다.

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/db.yaml
kubectl apply -f k8s/otel-collector-xray.yaml
kubectl apply -f k8s/backend.yaml
kubectl apply -f k8s/frontend.yaml
```

## OpenTelemetry Tracing

백엔드는 OpenTelemetry로 trace를 만들고 OTLP HTTP로 Collector에 전송합니다.
Collector 설정에 따라 AWS X-Ray 또는 Grafana Tempo로 보낼 수 있습니다.

로컬 Docker Compose에서는 기본적으로 꺼져 있습니다.

```yaml
OTEL_TRACING_ENABLED: "false"
```

Kubernetes 예시에서는 켜져 있고, ADOT Collector로 trace를 보냅니다.

```yaml
OTEL_TRACING_ENABLED: "true"
OTEL_SERVICE_NAME: stock-demo-api
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: http://otel-collector.aws-observability:4318/v1/traces
OTEL_EXPORTER_OTLP_TRACES_PROTOCOL: http/protobuf
```

X-Ray로 보낼 때는 `k8s/otel-collector-xray.yaml`의 ADOT Collector가 `awsxray` exporter를 사용합니다.
Tempo로 보내려면 Collector exporter만 Tempo용 OTLP exporter로 바꾸면 됩니다.

또한 X-Ray로 보낼 경우 노드 IAM Role 또는 Pod IAM Role에는 X-Ray trace 전송 권한이 필요합니다.

X-Ray에서 기대할 수 있는 흐름은 다음과 같습니다.

```text
GET /api/recommendations
  -> stock-demo-api
  -> PostgreSQL SELECT recommendations
```

Loki는 trace 저장소가 아니라 log 저장소입니다. 요청 흐름을 보려면 X-Ray, Grafana Tempo, Jaeger 같은 tracing backend가 필요합니다. Loki는 trace id가 포함된 로그를 검색하거나, trace와 로그를 연결하는 용도로 같이 쓰는 것이 일반적입니다.

## Load Test Demo

Locust로 정상 요청, 400 에러, 500 에러, 느린 응답을 일부러 만들 수 있습니다.

먼저 앱을 실행합니다.

```bash
docker compose up --build
```

다른 터미널에서 Locust를 실행합니다.

```bash
docker compose --profile loadtest up locust
```

브라우저에서 Locust UI에 접속합니다.

```text
http://localhost:8089
```

Host는 이미 `http://frontend`로 설정되어 있으므로 사용자 수와 증가율만 입력하면 됩니다.
예를 들어 데모에서는 다음 정도면 충분합니다.

```text
Number of users: 20
Ramp up: 5
```

Locust가 호출하는 경로는 다음과 같습니다.

```text
GET /api/recommendations
GET /api/demo/bad-request
GET /api/demo/server-error
GET /api/demo/slow
```

트레이싱을 켠 Kubernetes 환경에서는 400/500/slow 요청도 X-Ray 또는 Tempo에서 확인할 수 있습니다.

## Sample Prices

샘플 데이터의 `currentPrice`는 2026-05-12 KST에 조회한 StockAnalysis 지연 시세 또는 마지막 종가를 참고했습니다.
실시간 자동 갱신 데이터가 아니라 데모용 초기 데이터입니다.

## API

### `GET /api/recommendations`

추천 종목 목록을 반환합니다.

```json
[
  {
    "id": 1,
    "name": "LG이노텍",
    "ticker": "011070",
    "reason": "패키지 솔루션 영업이익 증가 예상",
    "currentPrice": 688000,
    "recommendedPrice": 577000,
    "recommendationDate": "2026-04-28"
  }
]
```
