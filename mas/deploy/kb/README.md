# Bedrock Knowledge Base (S3 Vectors) — SecOps 규정 RAG

SecOps `map_regulation`의 규정 검색을 로컬 파일 대신 Bedrock KB로 전환하기 위한 셋업.
교체형 설계(`app/retrieval.py`)라 **코드는 안 바뀌고 env만** 바꾼다.

- **발표/로컬**: `USE_BEDROCK_KB=false` (기본) — 레포 안 `regulations/*.md`로 검색. AWS 자격증명 불필요.
- **배포/실서비스**: `USE_BEDROCK_KB=true` + `BEDROCK_KB_ID=<id>` — 아래에서 만든 KB로 검색.

S3 Vectors는 OpenSearch Serverless와 달리 **상시 과금이 없고(사용한 만큼만)**, 서울 리전을 지원한다.
(우리가 로컬로 갔던 이유였던 비용 절벽이 S3 Vectors로 해소됨.)

---

## 사전 준비
1. **리전**: `ap-northeast-2` (서울). 임베딩 모델·KB·S3 버킷 모두 같은 리전.
2. **모델 액세스**: Bedrock 콘솔에서 **Titan Text Embeddings V2** (`amazon.titan-embed-text-v2:0`) 액세스 활성화.
3. **자격증명**: 계정 공유 → MFA 세션 (`aws sts get-session-token --serial-number <mfa-arn> --token-code <코드>`).

## 1) 규정 문서를 S3에 업로드
```
python deploy/kb/upload_regulations.py --bucket <SOURCE_BUCKET> --prefix regulations/
```
버킷이 없으면 생성하고, `pods/secops/orchestrator/app/regulations/*.md` 4개를 업로드한다.

## 2) KB 생성 — 콘솔 Quick Create (권장, 가장 안전)
Bedrock 콘솔 → **Knowledge Bases → Create knowledge base**:
- **IAM**: 새 서비스 역할 자동 생성
- **데이터 소스**: Amazon S3 → `s3://<SOURCE_BUCKET>/regulations/`
- **청킹**: Fixed-size (기본)
- **임베딩 모델**: Titan Text Embeddings V2 (1024차원)
- **벡터 스토어**: *S3 vector bucket* → **Quick create a new vector store**
  → Bedrock이 S3 벡터 버킷 + 인덱스를 자동 생성 (차원/거리계량 자동 매칭)
- 생성 후 데이터 소스 **Sync** (임베딩 생성·저장)

생성되면 **Knowledge base ID**를 복사 → `BEDROCK_KB_ID`.

### CLI 대안 (스크립트화할 경우)
벡터 버킷/인덱스를 먼저 생성(`aws s3vectors ...` 또는 콘솔)한 뒤:
```
aws bedrock-agent create-knowledge-base \
  --name secops-regulations \
  --role-arn arn:aws:iam::<ACCOUNT>:role/<KB_ROLE> \
  --knowledge-base-configuration '{"type":"VECTOR","vectorKnowledgeBaseConfiguration":{"embeddingModelArn":"arn:aws:bedrock:ap-northeast-2::foundation-model/amazon.titan-embed-text-v2:0","embeddingModelConfiguration":{"bedrockEmbeddingModelConfiguration":{"dimensions":1024,"embeddingDataType":"FLOAT32"}}}}' \
  --storage-configuration '{"type":"S3_VECTORS","s3VectorsConfiguration":{"vectorBucketArn":"arn:aws:s3vectors:ap-northeast-2:<ACCOUNT>:bucket/<VBUCKET>","indexArn":"arn:aws:s3vectors:ap-northeast-2:<ACCOUNT>:bucket/<VBUCKET>/index/<VINDEX>"}}' \
  --region ap-northeast-2
```
이후 `aws bedrock-agent create-data-source`(s3Configuration) + `start-ingestion-job`로 Sync.
(차원은 임베딩 모델과 인덱스가 반드시 일치 — Titan v2 = 1024, 거리계량 Cosine 권장.)

## 3) 확인 (스모크 테스트)
```
$env:BEDROCK_KB_ID="<id>"
python deploy/kb/kb_smoketest.py "비정상 외부 송신 트래픽 데이터 유출"
```
규정 청크가 score와 함께 나오면 OK. (결과 0건이면 Sync 완료 여부·쿼리·KB_ID 확인)

## 4) 워커에 적용
배포 매니페스트(SecOps 워커)에 env 추가:
```
USE_BEDROCK_KB=true
BEDROCK_KB_ID=<id>
AWS_REGION=ap-northeast-2
```
+ 워커 Pod ServiceAccount에 해당 KB에 대한 `bedrock:Retrieve` 권한.

## 비용 / 정리
- S3 Vectors는 저장·쿼리 사용량 기반 — 규정 몇 건은 무시할 수준.
- 정리 순서: KB 삭제 → S3 벡터 버킷/인덱스 삭제 → 소스 S3 버킷 삭제.

## ⚠️ 발표 주의
발표는 발표자 PC(자격증명 없음)라 **`USE_BEDROCK_KB=false`(로컬)** 로 시연.
KB는 배포/실서비스 경로다. 둘은 교체형으로 **공존**하며, 코드는 동일하다.
