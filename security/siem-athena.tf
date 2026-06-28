# =============================================
# SIEM — Athena 저장·검색 레이어
#
# 대상 소스:
#   · CloudTrail  — ilpumjinro-cloudtrail-logs-locked-v3  (JSON.gz, 멀티리전)
#   · ALB Logs    — financial-alb-access-logs-{acct}       (공백 구분 텍스트 .log.gz)
#   · Prowler     — financial-prowler-findings-{acct}       (.ocsf.json, JSON 배열)
#
# 설계 원칙:
#   · Partition Projection 전용 — 크롤러/MSCK REPAIR TABLE 금지
#   · destroy/apply 환경 대응 — DDL·설정 위주, ETL 변환 인프라 없음
#   · 기존 key-s3 CMK 재사용 (신규 CMK 생성 없음)
# =============================================


# ─────────────────────────────────────────────
# S3 — SIEM Athena 쿼리 결과 버킷
#
# · 네이밍: financial-siem-athena-results-{acct}-{region}
#           finops 패턴 준수 (financial-finops-athena-results-{acct}-{region})
# · 암호화: key-s3 CMK — ALB와 달리 Athena는 SSE-KMS 정상 지원
# · lifecycle 7일: 쿼리 결과는 임시 파일, 불필요한 스토리지 비용 방지
# · force_destroy: destroy/apply 환경에서 잔여 객체로 인한 삭제 실패 방지
# ─────────────────────────────────────────────
resource "aws_s3_bucket" "siem_athena_results" {
  bucket        = "financial-siem-athena-results-${var.account_id}-${var.aws_region}"
  force_destroy = true

  tags = {
    Name               = "financial-siem-athena-results"
    Project            = "ilpumjinro"
    ManagedBy          = "terraform"
    Owner              = "security"
    Service            = "SIEM"
    Environment        = "all"
    DataClassification = "Restricted"
  }
}

resource "aws_s3_bucket_public_access_block" "siem_athena_results" {
  bucket = aws_s3_bucket.siem_athena_results.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "siem_athena_results" {
  bucket = aws_s3_bucket.siem_athena_results.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.key_s3_arn
    }
    # 버킷 수준 KMS 캐싱 — 객체당 API 호출 대신 버킷당 data key 사용 → 비용 절감
    bucket_key_enabled = true
  }
}

# 쿼리 결과는 임시 데이터 → 7일 후 자동 삭제
resource "aws_s3_bucket_lifecycle_configuration" "siem_athena_results" {
  bucket = aws_s3_bucket.siem_athena_results.id

  rule {
    id     = "expire-query-results"
    status = "Enabled"

    filter { prefix = "" }

    expiration {
      days = 7
    }
  }

  depends_on = [aws_s3_bucket_public_access_block.siem_athena_results]
}


# ─────────────────────────────────────────────
# Athena Workgroup — siem
#
# · bytes_scanned_cutoff_per_query = 1 GiB:
#     파티션 필터 없는 풀스캔 실수 실행 시 자동 취소 (과금 차단기)
# · enforce_workgroup_configuration = true:
#     사용자가 클라이언트 측에서 결과 버킷·암호화 설정을 오버라이드 못 하게 강제
# · finops-cur와 완전 분리 — 독립적 스캔 한도·결과 버킷·CloudWatch 메트릭
# ─────────────────────────────────────────────
resource "aws_athena_workgroup" "siem" {
  name        = "siem"
  description = "SIEM 분석 전용 워크그룹 — CloudTrail/ALB/Prowler 쿼리, 1GiB 스캔 한도"
  state       = "ENABLED"

  configuration {
    # 1 GiB 초과 쿼리 자동 취소 — 실수로 파티션 필터 누락 시 과금 차단
    bytes_scanned_cutoff_per_query = 1073741824

    # 사용자가 워크그룹 설정을 클라이언트 측에서 우회하지 못하게 강제
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.siem_athena_results.bucket}/query-results/"

      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = var.key_s3_arn
      }
    }
  }

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "SIEM"
    Environment = "all"
  }

  depends_on = [
    aws_s3_bucket_public_access_block.siem_athena_results,
    aws_s3_bucket_server_side_encryption_configuration.siem_athena_results,
  ]
}


# ─────────────────────────────────────────────
# Glue Database — siem
#
# CloudTrail/ALB/Prowler 세 테이블의 논리 컨테이너.
# 이름 "siem": 단일 DB에서 보안 소스 전체를 일관되게 관리.
# ─────────────────────────────────────────────
resource "aws_glue_catalog_database" "siem" {
  name        = "siem"
  description = "SIEM 분석용 Glue DB — CloudTrail/ALB Access Logs/Prowler OCSF 외부 테이블"
}


# ─────────────────────────────────────────────
# Glue 외부 테이블 (1/3) — cloudtrail
#
# 소스: s3://ilpumjinro-cloudtrail-logs-locked-v3/
#         AWSLogs/{acct}/CloudTrail/{region}/{yyyy}/{mm}/{dd}/
# SerDe: CloudTrailSerde
#   · JSON.gz 파일 내 Records[] 배열 래퍼를 자동 언래핑 → 각 이벤트가 1행
#   · SpecialEMRInputFormat: gzip 해제 + CloudTrail JSON 구조 처리
# Partition Projection: region / year / month / day
#   · region enum: 버킷에 17개 리전 폴더 확인됨
#                  주 쿼리 대상 2개만 포함 (추가 리전은 values에 콤마로 추가)
# ─────────────────────────────────────────────
resource "aws_glue_catalog_table" "cloudtrail" {
  database_name = aws_glue_catalog_database.siem.name
  name          = "cloudtrail"
  description   = "CloudTrail 멀티리전 관리 이벤트 (WriteOnly) — Partition Projection"
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "projection.enabled"     = "true"
    "projection.region.type" = "enum"
    # 실제 로그 확인 리전 17개 중 주 쿼리 대상 2개 — 추가 리전 필요 시 여기에 추가
    "projection.region.values" = "us-east-1,ap-northeast-2"
    "projection.year.type"     = "integer"
    "projection.year.range"    = "2026,2030"
    "projection.year.digits"   = "4"
    "projection.month.type"    = "integer"
    "projection.month.range"   = "1,12"
    "projection.month.digits"  = "2"
    "projection.day.type"      = "integer"
    "projection.day.range"     = "1,31"
    "projection.day.digits"    = "2"
    # $${...}: Terraform 이스케이프 → AWS에는 ${...} 전달 → Athena가 파티션 값으로 치환
    "storage.location.template" = "s3://ilpumjinro-cloudtrail-logs-locked-v3/AWSLogs/${var.account_id}/CloudTrail/$${region}/$${year}/$${month}/$${day}/"
    "classification"            = "cloudtrail"
  }

  # 파티션 키 — storage_descriptor.columns에는 포함하지 않음 (Hive 외부 테이블 표준)
  partition_keys {
    name = "region"
    type = "string"
  }
  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
  partition_keys {
    name = "day"
    type = "string"
  }

  storage_descriptor {
    # 루트 경로 — Athena는 storage.location.template로 실제 파티션 경로 결정
    location = "s3://ilpumjinro-cloudtrail-logs-locked-v3/AWSLogs/${var.account_id}/CloudTrail/"
    # gzip JSON 해제 + CloudTrail Records[] 구조 처리 전용 InputFormat
    input_format  = "com.amazon.emr.cloudtrail.CloudTrailInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      name = "cloudtrail"
      # Records[] 배열 래퍼 제거 + 중첩 JSON → Hive 타입 자동 변환
      serialization_library = "com.amazon.emr.hive.serde.CloudTrailSerde"
      parameters = {
        "serialization.format" = "1"
      }
    }

    # CloudTrail 표준 컬럼 스키마 (파티션 키 region/year/month/day 제외)
    columns {
      name = "eventversion"
      type = "string"
    }
    columns {
      name = "useridentity"
      # 자주 쿼리하는 필드만 struct 정의; 나머지는 json_extract_scalar() 사용
      type = "struct<type:string,principalid:string,arn:string,accountid:string,invokedby:string,accesskeyid:string,username:string,sessioncontext:struct<attributes:struct<mfaauthenticated:string,creationdate:string>,sessionissuer:struct<type:string,principalid:string,arn:string,accountid:string,username:string>>>"
    }
    columns {
      name = "eventtime"
      type = "string"
    }
    columns {
      name = "eventsource"
      type = "string"
    }
    columns {
      name = "eventname"
      type = "string"
    }
    columns {
      name = "awsregion"
      type = "string"
    }
    columns {
      name = "sourceipaddress"
      type = "string"
    }
    columns {
      name = "useragent"
      type = "string"
    }
    columns {
      name = "errorcode"
      type = "string"
    }
    columns {
      name = "errormessage"
      type = "string"
    }
    columns {
      name    = "requestparameters"
      type    = "string"
      comment = "JSON 문자열 원형 보존 → 쿼리 시 json_extract_scalar() 사용"
    }
    columns {
      name    = "responseelements"
      type    = "string"
      comment = "JSON 문자열 원형 보존 → 쿼리 시 json_extract_scalar() 사용"
    }
    columns {
      name = "additionaleventdata"
      type = "string"
    }
    columns {
      name = "requestid"
      type = "string"
    }
    columns {
      name = "eventid"
      type = "string"
    }
    columns {
      name = "eventtype"
      type = "string"
    }
    columns {
      name = "apiversion"
      type = "string"
    }
    columns {
      name = "readonly"
      type = "string"
    }
    columns {
      name = "resources"
      type = "array<struct<arn:string,accountid:string,type:string>>"
    }
    columns {
      name = "recipientaccountid"
      type = "string"
    }
    columns {
      name = "serviceeventdetails"
      type = "string"
    }
    columns {
      name = "sharedeventid"
      type = "string"
    }
    columns {
      name = "vpcendpointid"
      type = "string"
    }
  }
}


# ─────────────────────────────────────────────
# Glue 외부 테이블 (2/3) — alb
#
# 소스: s3://financial-alb-access-logs-{acct}/
#         alb/AWSLogs/{acct}/elasticloadbalancing/{region}/{yyyy}/{mm}/{dd}/
# SerDe: RegexSerDe + AWS 공식 ALB 정규식 (33개 필드 캡처)
# 포맷: 공백 구분 텍스트 (.log.gz) — gzip은 TextInputFormat이 자동 처리
# Partition Projection: region / year / month / day
#   · region enum: ap-northeast-2 단일 (버킷 실적재 확인)
# ─────────────────────────────────────────────
resource "aws_glue_catalog_table" "alb" {
  database_name = aws_glue_catalog_database.siem.name
  name          = "alb"
  description   = "ALB Access Logs (stockweb, ap-northeast-2) — Partition Projection"
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "projection.enabled"     = "true"
    "projection.region.type" = "enum"
    # 현재 로그 적재 리전 — 새 리전 ALB 추가 시 values 확장
    "projection.region.values"  = "ap-northeast-2"
    "projection.year.type"      = "integer"
    "projection.year.range"     = "2026,2030"
    "projection.year.digits"    = "4"
    "projection.month.type"     = "integer"
    "projection.month.range"    = "1,12"
    "projection.month.digits"   = "2"
    "projection.day.type"       = "integer"
    "projection.day.range"      = "1,31"
    "projection.day.digits"     = "2"
    "storage.location.template" = "s3://financial-alb-access-logs-${var.account_id}/alb/AWSLogs/${var.account_id}/elasticloadbalancing/$${region}/$${year}/$${month}/$${day}/"
    "classification"            = "text"
  }

  partition_keys {
    name = "region"
    type = "string"
  }
  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
  partition_keys {
    name = "day"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://financial-alb-access-logs-${var.account_id}/alb/AWSLogs/${var.account_id}/elasticloadbalancing/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      name                  = "alb"
      serialization_library = "org.apache.hadoop.hive.serde2.RegexSerDe"
      parameters = {
        "serialization.format" = "1"
        # AWS 공식 ALB 액세스 로그 정규식 (33개 캡처 그룹)
        # 출처: https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-access-logs.html
        # HCL 이스케이프: \" → 리터럴 큰따옴표 / [^\\s] → [^\s] (비공백 문자 클래스)
        "input.regex" = "([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*):([0-9]*) ([^ ]*)[:-]([0-9]*) ([-.0-9]*) ([-.0-9]*) ([-.0-9]*) (|[-0-9]*) (-|[-0-9]*) ([-0-9]*) ([-0-9]*) \"([^ ]*) (.*) (- |[^ ]*)\" \"([^\"]*)\" ([A-Z0-9-_]+) ([A-Za-z0-9.-]*) ([^ ]*) \"([^\"]*)\" \"([^\"]*)\" \"([^\"]*)\" ([-.0-9]*) ([^ ]*) \"([^\"]*)\" \"([^\"]*)\" \"([^ ]*)\" \"([^\\s]+?)\" \"([^\\s]+)\" \"([^ ]*)\" \"([^ ]*)\" ?([^ ]*)?"
      }
    }

    # 정규식 캡처 그룹 순서와 1:1 대응 (33개)
    # elb_status_code / target_status_code: "-" 값 존재 가능 → string 유지
    # request_processing_time 등: -1(미처리) 또는 소수 → double로 파싱 가능
    columns {
      name = "type"
      type = "string"
    }
    columns {
      name = "time"
      type = "string"
    }
    columns {
      name = "elb"
      type = "string"
    }
    columns {
      name = "client_ip"
      type = "string"
    }
    columns {
      name = "client_port"
      type = "string"
    }
    columns {
      name = "target_ip"
      type = "string"
    }
    columns {
      name = "target_port"
      type = "string"
    }
    columns {
      name = "request_processing_time"
      type = "double"
    }
    columns {
      name = "target_processing_time"
      type = "double"
    }
    columns {
      name = "response_processing_time"
      type = "double"
    }
    columns {
      name = "elb_status_code"
      type = "string"
    }
    columns {
      name = "target_status_code"
      type = "string"
    }
    columns {
      name = "received_bytes"
      type = "bigint"
    }
    columns {
      name = "sent_bytes"
      type = "bigint"
    }
    columns {
      name = "request_verb"
      type = "string"
    }
    columns {
      name = "request_url"
      type = "string"
    }
    columns {
      name = "request_proto"
      type = "string"
    }
    columns {
      name = "user_agent"
      type = "string"
    }
    columns {
      name = "ssl_cipher"
      type = "string"
    }
    columns {
      name = "ssl_protocol"
      type = "string"
    }
    columns {
      name = "target_group_arn"
      type = "string"
    }
    columns {
      name = "trace_id"
      type = "string"
    }
    columns {
      name = "domain_name"
      type = "string"
    }
    columns {
      name = "chosen_cert_arn"
      type = "string"
    }
    columns {
      name = "matched_rule_priority"
      type = "string"
    }
    columns {
      name = "request_creation_time"
      type = "string"
    }
    columns {
      name = "actions_executed"
      type = "string"
    }
    columns {
      name = "redirect_url"
      type = "string"
    }
    columns {
      name = "lambda_error_reason"
      type = "string"
    }
    columns {
      name = "target_port_list"
      type = "string"
    }
    columns {
      name = "target_status_code_list"
      type = "string"
    }
    columns {
      name = "classification"
      type = "string"
    }
    columns {
      name = "classification_reason"
      type = "string"
    }
  }
}


# ─────────────────────────────────────────────
# Glue 외부 테이블 (3/3) — prowler
#
# 소스: s3://financial-prowler-findings-{acct}/{YYYY-MM-DD}/ocsf/
#   buildspec-prowler.yml: .ocsf.json은 ${date}/ocsf/, csv/html은 ${date}/reports/ 로 분리 업로드
#   → Athena 스캔 대상을 ocsf/ 하위만으로 한정 (낭비 50% 제거)
# SerDe: OpenX JSON (org.openx.data.jsonserde.JsonSerDe)
#   · strip.outer.array=TRUE: 파일이 [{...},...] JSON 배열로 시작 (실파일 확인 완료)
#   · ignore.malformed.json=TRUE: 예기치 않은 비JSON 파일 혼입 시 안전망
# Partition Projection: date (YYYY-MM-DD)
#   · NOW: Athena가 현재 날짜를 자동 계산 → 새 스캔 결과 즉시 포함, 파티션 추가 불필요
# OCSF 스키마: Prowler v4, OCSF v1.1 Compliance Finding 클래스 기준
#   · 깊은 중첩 필드는 string으로 수신 → 쿼리 시 json_extract_scalar() 사용
# ─────────────────────────────────────────────
resource "aws_glue_catalog_table" "prowler" {
  database_name = aws_glue_catalog_database.siem.name
  name          = "prowler"
  description   = "Prowler OCSF 보안 스캔 결과 (ISMS-P, ap-northeast-2) — Partition Projection"
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "projection.enabled"   = "true"
    "projection.date.type" = "date"
    # Java SimpleDateFormat 패턴 (Athena 파티션 projection 표준)
    "projection.date.format" = "yyyy-MM-dd"
    # NOW: Athena 런타임 현재 날짜로 자동 치환 → 스캔 주기와 무관하게 최신 결과 포함
    "projection.date.range"         = "2026-01-01,NOW"
    "projection.date.interval"      = "1"
    "projection.date.interval.unit" = "DAYS"
    # buildspec-prowler.yml과 경로 정합: .ocsf.json은 ${date}/ocsf/ 에만 업로드됨
    "storage.location.template" = "s3://financial-prowler-findings-${var.account_id}/$${date}/ocsf/"
    "classification"            = "json"
  }

  partition_keys {
    name    = "date"
    type    = "string"
    comment = "스캔 실행 날짜 (YYYY-MM-DD) — CodeBuild 빌드 날짜와 동일"
  }

  storage_descriptor {
    location      = "s3://financial-prowler-findings-${var.account_id}/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      name                  = "prowler_ocsf"
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
      parameters = {
        # 파일이 [{...},{...}] 형식 → 배열 외부 괄호 제거 후 각 원소를 1행으로 처리
        "strip.outer.array" = "TRUE"
        # .csv/.html/compliance/* 파일이 JSON 파싱 실패 시 조용히 건너뜀
        "ignore.malformed.json" = "TRUE"
        "serialization.format"  = "1"
      }
    }

    # OCSF v1.1 Compliance Finding 클래스 최상위 필드
    # 참조: https://schema.ocsf.io/1.1.0/classes/compliance_finding
    columns {
      name    = "message"
      type    = "string"
      comment = "사람이 읽을 수 있는 점검 결과 요약"
    }
    columns {
      name    = "metadata"
      type    = "struct<event_code:string,product:struct<name:string,vendor_name:string,version:string>,version:string>"
      comment = "event_code = Prowler 점검 ID (예: accessanalyzer_enabled)"
    }
    columns {
      name    = "severity"
      type    = "string"
      comment = "Informational / Low / Medium / High / Critical"
    }
    columns {
      name = "severity_id"
      type = "int"
    }
    columns {
      name    = "status"
      type    = "string"
      comment = "Pass / Fail / Unknown / Error"
    }
    columns {
      name = "status_id"
      type = "int"
    }
    columns {
      name = "type_uid"
      type = "bigint"
    }
    columns {
      name = "type_name"
      type = "string"
    }
    columns {
      name = "category_uid"
      type = "int"
    }
    columns {
      name = "category_name"
      type = "string"
    }
    columns {
      name = "class_uid"
      type = "int"
    }
    columns {
      name = "class_name"
      type = "string"
    }
    columns {
      name    = "time"
      type    = "bigint"
      comment = "Unix 타임스탬프 (밀리초) → from_unixtime(time/1000) 으로 변환"
    }
    columns {
      name = "activity_id"
      type = "int"
    }
    columns {
      name = "activity_name"
      type = "string"
    }
    columns {
      name    = "cloud"
      type    = "struct<account:struct<uid:string>,provider:string,region:string>"
      comment = "cloud.region = 점검 대상 AWS 리전"
    }
    columns {
      name    = "resources"
      type    = "array<struct<uid:string,type:string,name:string>>"
      comment = "점검 대상 리소스 목록"
    }
    columns {
      name    = "compliance"
      type    = "struct<requirements:array<string>,status:string>"
      comment = "ISMS-P 등 컴플라이언스 항목 매핑"
    }
    columns {
      name    = "finding_info"
      type    = "struct<uid:string,title:string,desc:string>"
      comment = "OCSF v1.1 점검 항목 상세 (구버전 Prowler는 finding 필드명 사용)"
    }
    columns {
      name    = "remediation"
      type    = "struct<desc:string>"
      comment = "수정 방법 설명"
    }
    columns {
      name    = "risk_score"
      type    = "int"
      comment = "위험 점수 (옵션 필드 — 없으면 NULL)"
    }
  }
}


# ─────────────────────────────────────────────
# IAM Role — SIEM Athena 쿼리 전용
#
# 신뢰 주체: arn:aws:iam::{acct}:user/security (기존 kms-admin-role 패턴 — iam/roles.tf:35)
# 현 단계에서는 보안 담당자 전용. MAS Phase에서 Agent 신뢰 주체(Bedrock Agent 또는
# Lambda 실행 역할) 추가 예정 — Principal.AWS 배열에 Agent ARN 추가하거나
# Principal.Service에 bedrock.amazonaws.com 추가.
# ─────────────────────────────────────────────
resource "aws_iam_role" "siem_athena_query" {
  name        = "financial-siem-athena-query-role"
  description = "SIEM Athena query execution role - AssumeRole by security user, reused by MAS agent"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowSecurityUser"
      Effect = "Allow"
      Principal = {
        # security IAM 유저만 허용 (iam/roles.tf 동일 패턴)
        # MAS Phase: Agent 신뢰 주체 이 배열에 추가 예정
        AWS = "arn:aws:iam::${var.account_id}:user/security"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "SIEM"
    Environment = "all"
  }
}

# ─────────────────────────────────────────────
# IAM 인라인 정책 — SIEM Athena 쿼리 권한
#
# 패턴: aws_iam_role_policy 인라인 (security/ 모듈 표준 — prowler.tf, pii_scan.tf 동일)
# 원칙: 최소 권한. Athena·Glue·S3·KMS 각각 필요한 Action만.
# ─────────────────────────────────────────────
resource "aws_iam_role_policy" "siem_athena_query" {
  name = "financial-siem-athena-query-policy"
  role = aws_iam_role.siem_athena_query.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Athena 쿼리 실행 — siem 워크그룹으로만 한정
        # GetWorkGroup: 워크그룹 설정(스캔 한도·결과 위치) 조회에 필요
        Sid    = "AthenaQuery"
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:StopQueryExecution",
          "athena:GetWorkGroup"
        ]
        Resource = aws_athena_workgroup.siem.arn
      },
      {
        # Glue 메타데이터 읽기 — siem DB·테이블로만 한정
        # catalog ARN은 Glue 리소스 접근의 필수 상위 경로
        Sid    = "GlueReadMetadata"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetPartition",
          "glue:GetPartitions"
        ]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:database/${aws_glue_catalog_database.siem.name}",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:table/${aws_glue_catalog_database.siem.name}/*"
        ]
      },
      {
        # S3 원본 로그 버킷 3개 읽기
        # · CloudTrail: ilpumjinro-cloudtrail-logs-locked-v3 (Object Lock + key-cloudtrail 암호화)
        # · ALB:        financial-alb-access-logs-{acct} (AES256, KMS 불필요)
        # · Prowler:    financial-prowler-findings-{acct} (key-s3 암호화)
        Sid    = "S3ReadSourceBuckets"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::ilpumjinro-cloudtrail-logs-locked-v3",
          "arn:aws:s3:::ilpumjinro-cloudtrail-logs-locked-v3/*",
          "arn:aws:s3:::financial-alb-access-logs-${var.account_id}",
          "arn:aws:s3:::financial-alb-access-logs-${var.account_id}/*",
          "arn:aws:s3:::financial-prowler-findings-${var.account_id}",
          "arn:aws:s3:::financial-prowler-findings-${var.account_id}/*"
        ]
      },
      {
        # S3 쿼리 결과 버킷 읽기·쓰기
        # GetBucketLocation: Athena가 버킷 리전 확인 시 내부적으로 호출
        Sid    = "S3ResultsBucket"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          aws_s3_bucket.siem_athena_results.arn,
          "${aws_s3_bucket.siem_athena_results.arn}/*"
        ]
      },
      {
        # KMS — key-s3 (results 버킷 쓰기 + prowler 버킷 읽기)
        # GenerateDataKey: results 버킷에 쿼리 결과 쓸 때 필요
        # Decrypt:         prowler 버킷(SSE-KMS, key-s3) 읽을 때 필요
        Sid    = "KMSKeyS3"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey"
        ]
        Resource = var.key_s3_arn
      },
      {
        # KMS — key-cloudtrail (CloudTrail 로그 파일 복호화 전용)
        # CloudTrail trail이 key-cloudtrail로 로그 내용을 암호화(security/cloudtrail.tf:86)
        # S3 SSE(key-s3)와 별개 레이어 — 이 Decrypt 없으면 CloudTrail 테이블 쿼리 실패
        # GenerateDataKey 불필요 — CloudTrail 로그는 읽기 전용
        Sid    = "KMSKeyCloudTrail"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = var.kms_key_cloudtrail_arn
      }
    ]
  })
}


# ─────────────────────────────────────────────
# 검증용 샘플 쿼리 (apply 후 Athena Console → siem 워크그룹 선택 후 실행)
#
# ※ 반드시 파티션 필터(WHERE region= / year= / date=) 포함할 것
#    미포함 시 bytes_scanned_cutoff(1 GiB) 초과로 쿼리 자동 취소됨
#
# [1] CloudTrail — ap-northeast-2 IAM 오류 이벤트 (특정 날짜)
#
#   SELECT eventtime, eventname, useridentity.arn,
#          sourceipaddress, errorcode, errormessage
#   FROM   siem.cloudtrail
#   WHERE  region = 'ap-northeast-2'
#     AND  year   = '2026'
#     AND  month  = '06'
#     AND  day    = '27'
#     AND  eventsource = 'iam.amazonaws.com'
#     AND  errorcode IS NOT NULL
#   ORDER BY eventtime DESC
#   LIMIT 100;
#
# [2] ALB — 5xx 에러 (특정 날짜)
#
#   SELECT time, elb_status_code, target_status_code,
#          client_ip, request_verb, request_url
#   FROM   siem.alb
#   WHERE  region = 'ap-northeast-2'
#     AND  year   = '2026'
#     AND  month  = '06'
#     AND  day    = '27'
#     AND  elb_status_code LIKE '5%'
#   ORDER BY time DESC
#   LIMIT 100;
#
# [3] Prowler — 최신 스캔 HIGH/CRITICAL Fail 항목
#
#   SELECT date,
#          metadata.event_code,
#          message,
#          severity,
#          status,
#          cloud.region,
#          resources[1].uid AS resource_uid
#   FROM   siem.prowler
#   WHERE  date   = '2026-06-23'
#     AND  status = 'FAIL'
#     AND  severity IN ('High', 'Critical')
#   ORDER BY severity_id DESC
#   LIMIT 50;
# ─────────────────────────────────────────────