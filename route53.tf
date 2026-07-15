# ── Hosted Zone ───────────────────────────────────────────────────────────────

resource "aws_route53_zone" "main" {
  name = "ilpumjinro.store"
}

# ── ACM 인증서 (와일드카드 + 루트) ──────────────────────────────────────────

resource "aws_acm_certificate" "main" {
  domain_name               = "ilpumjinro.store"
  subject_alternative_names = ["*.ilpumjinro.store"]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "acm_validation" {
  for_each = {
    for dvo in aws_acm_certificate.main.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = aws_route53_zone.main.zone_id
}

resource "aws_acm_certificate_validation" "main" {
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = [for record in aws_route53_record.acm_validation : record.fqdn]
}

# ── Health Check (AWS ALB 상태 감시) ──────────────────────────────────────────

# stock-web ALB는 service 클러스터 Ingress(AWS LB Controller)가 동적으로 생성하므로
# DNS·zone_id를 하드코딩하지 않고 태그로 자동 조회한다. 복수형 data.aws_lbs는
# 매칭 0개여도 에러가 없어(단수형 aws_lb는 0개 시 plan 실패), ALB가 아직 없는
# 재구축 초기에도 plan이 깨지지 않으며, ALB가 생기면 레코드가 자동 활성화된다.
data "aws_lbs" "service" {
  tags = {
    "ingress.k8s.aws/stack" = "stock-demo/stock-web"
  }
}

locals {
  # ALB가 조회되면 1, 없으면 0 — Route53 레코드/헬스체크 생성 여부를 자동 결정
  service_alb_enabled = length(data.aws_lbs.service.arns) > 0 ? 1 : 0
}

data "aws_lb" "service" {
  count = local.service_alb_enabled
  arn   = tolist(data.aws_lbs.service.arns)[0]
}

# Route 53은 ALB DNS 이름을 Host 헤더로 사용한다. 이 이름은 앱 Ingress의 host 규칙과
# 일치하지 않으므로, ALB로 직접 향하는 전용 상태 검사 도메인을 사용한다.
resource "aws_route53_record" "aws_health" {
  count   = local.service_alb_enabled
  zone_id = aws_route53_zone.main.zone_id
  name    = "health.ilpumjinro.store"
  type    = "A"

  alias {
    name                   = data.aws_lb.service[0].dns_name
    zone_id                = data.aws_lb.service[0].zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_health_check" "aws_primary" {
  count = local.service_alb_enabled

  fqdn               = aws_route53_record.aws_health[0].fqdn
  port               = 443
  type               = "HTTPS"
  resource_path      = "/"
  failure_threshold  = 3
  request_interval   = 30
  enable_sni         = true
  invert_healthcheck = false

  # DR workflows own the temporary inversion used to force failover tests.
  # A routine Terraform apply must not silently route traffic back to AWS.
  lifecycle {
    ignore_changes = [invert_healthcheck]
  }

  tags = {
    Name = "financial-stock-web-health-check"
  }
}

# GCP secondary도 독립적으로 HTTPS 상태를 확인한다. Primary가 실패했더라도
# GCP Gateway가 준비되지 않은 상태면 Route 53이 정상 서비스처럼 응답하지 않는다.
resource "aws_route53_health_check" "gcp_secondary" {
  count = var.gcp_service_ip != "" ? 1 : 0

  fqdn              = "gcp.ilpumjinro.store"
  port              = 443
  type              = "HTTPS"
  resource_path     = "/"
  failure_threshold = 3
  request_interval  = 30
  enable_sni        = true

  tags = {
    Name = "financial-gcp-stock-web-health-check"
  }
}

# ── ilpumjinro.store — Failover (PRIMARY: AWS / SECONDARY: GCP) ──────────────

resource "aws_route53_record" "root_primary" {
  count   = local.service_alb_enabled
  zone_id = aws_route53_zone.main.zone_id
  name    = "ilpumjinro.store"
  type    = "A"

  set_identifier  = "aws-primary"
  health_check_id = aws_route53_health_check.aws_primary[0].id

  failover_routing_policy {
    type = "PRIMARY"
  }

  alias {
    name                   = data.aws_lb.service[0].dns_name
    zone_id                = data.aws_lb.service[0].zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "root_secondary" {
  count   = var.gcp_service_ip != "" ? 1 : 0
  zone_id = aws_route53_zone.main.zone_id
  name    = "ilpumjinro.store"
  type    = "A"

  set_identifier  = "gcp-secondary"
  health_check_id = aws_route53_health_check.gcp_secondary[0].id
  ttl             = 60
  records         = [var.gcp_service_ip]

  failover_routing_policy {
    type = "SECONDARY"
  }
}

# ── aws.ilpumjinro.store → AWS ALB 직접 연결 ──────────────────────────────────

resource "aws_route53_record" "aws_direct" {
  count   = local.service_alb_enabled
  zone_id = aws_route53_zone.main.zone_id
  name    = "aws.ilpumjinro.store"
  type    = "A"

  alias {
    name                   = data.aws_lb.service[0].dns_name
    zone_id                = data.aws_lb.service[0].zone_id
    evaluate_target_health = true
  }
}

# ── gcp.ilpumjinro.store → GCP LB 직접 연결 ──────────────────────────────────

resource "aws_route53_record" "gcp_direct" {
  count   = var.gcp_service_ip != "" ? 1 : 0
  zone_id = aws_route53_zone.main.zone_id
  name    = "gcp.ilpumjinro.store"
  type    = "A"
  ttl     = 60
  records = [var.gcp_service_ip]
}

# ── aiops.ilpumjinro.store → AIOps Ingress ALB ────────────────────────────────

resource "aws_route53_record" "aiops" {
  count   = var.aiops_alb_dns_name != "" ? 1 : 0
  zone_id = aws_route53_zone.main.zone_id
  name    = "aiops.ilpumjinro.store"
  type    = "A"

  alias {
    name                   = var.aiops_alb_dns_name
    zone_id                = "Z35SXDOTRQ7X7K"
    evaluate_target_health = true
  }
}
