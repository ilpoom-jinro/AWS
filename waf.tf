# ──────────────────────────────────────────────────────────────────────────────
# WAFv2 (REGIONAL) — 인터넷향 서비스 ALB(stock-web) 보호
#
# 부착 방식: GitOps ingress 어노테이션(alb.ingress.kubernetes.io/wafv2-acl-arn)으로
#            aws-load-balancer-controller가 ALB에 연결한다. terraform association을
#            쓰지 않는 이유 = destroy/apply로 ALB 재생성 시 유실되기 때문(ingress
#            방식은 컨트롤러가 새 ALB에 자동 재연결).
#
# 롤아웃 원칙: 관리형 룰은 전부 Count 모드(override_action=count)로 시작 → WAF 로그로
#            오탐 관찰 → 문제 없는 룰부터 override_action을 none(=Block)으로 전환.
#            default_action=allow 이므로 Count 단계에선 어떤 정상 트래픽도 안 막힌다.
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_wafv2_web_acl" "service_alb" {
  name        = "financial-service-alb-waf"
  description = "REGIONAL WAF for the internet-facing service ALB - stock-web"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # ── priority 0: Route53 헬스체커는 항상 허용 ──────────────────────────────────
  # Route53 Failover 헬스체크(ALB 443 /)가 WAF에 막히면 PRIMARY(AWS)가 unhealthy로
  # 판정되어 SECONDARY(GCP)로 조용히 넘어간다. User-Agent로 식별해 선허용한다.
  rule {
    name     = "allow-route53-healthcheck"
    priority = 0

    action {
      allow {}
    }

    statement {
      byte_match_statement {
        search_string         = "Amazon-Route53-Health-Check-Service"
        positional_constraint = "CONTAINS"

        field_to_match {
          single_header {
            name = "user-agent"
          }
        }

        text_transformation {
          priority = 0
          type     = "NONE"
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "allow-route53-healthcheck"
      sampled_requests_enabled   = true
    }
  }

  # ── priority 10: AWS 관리형 Common Rule Set (Count) ───────────────────────────
  rule {
    name     = "aws-common"
    priority = 10

    override_action {
      count {} # Count 모드. Block 전환 시 -> none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-common"
      sampled_requests_enabled   = true
    }
  }

  # ── priority 20: Known Bad Inputs (Count) ─────────────────────────────────────
  rule {
    name     = "aws-known-bad-inputs"
    priority = 20

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  # ── priority 30: SQL Injection (Count) ────────────────────────────────────────
  # 금융 앱 JSON/API 페이로드에 오탐 위험이 가장 큰 룰 → 관찰 후 마지막에 Block 전환.
  rule {
    name     = "aws-sqli"
    priority = 30

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesSQLiRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-sqli"
      sampled_requests_enabled   = true
    }
  }

  # ── priority 40: Rate limit (Count) ───────────────────────────────────────────
  # rate 룰은 override_action이 아니라 action. 초기 count로 관찰 후 block 전환.
  # limit = 5분당 IP별 요청 수. 정상 피크의 2~3배로 넉넉히 시작.
  rule {
    name     = "rate-limit-per-ip"
    priority = 40

    action {
      count {}
    }

    statement {
      rate_based_statement {
        limit              = 3000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-limit-per-ip"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "financial-service-alb-waf"
    sampled_requests_enabled   = true
  }

  tags = {
    Name      = "financial-service-alb-waf"
    ManagedBy = "terraform"
  }
}

# ── WAF 로깅 → CloudWatch Logs ────────────────────────────────────────────────
# WAF 로깅 대상 로그그룹 이름은 반드시 "aws-waf-logs-" 로 시작해야 한다.
resource "aws_cloudwatch_log_group" "waf" {
  name              = "aws-waf-logs-financial-service-alb"
  retention_in_days = 30

  tags = {
    Name      = "aws-waf-logs-financial-service-alb"
    ManagedBy = "terraform"
  }
}

resource "aws_wafv2_web_acl_logging_configuration" "service_alb" {
  resource_arn            = aws_wafv2_web_acl.service_alb.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]
}

# gitops-platform-sync(ansible)가 frontend ingress의 wafv2-acl-arn 어노테이션을
# 주입할 때 ARN을 읽어가는 경로. seed CodeBuild는 격리 ops VPC에서 돌아
# wafv2 엔드포인트에 도달할 수 없으므로(엔드포인트 없음), VPC 엔드포인트가 있는
# SSM Parameter Store를 매개로 ARN을 전달한다.
resource "aws_ssm_parameter" "service_alb_waf_acl_arn" {
  name        = "/financial/waf/service-alb-acl-arn"
  description = "Service ALB WAFv2 REGIONAL web ACL ARN (consumed by gitops-platform-sync)"
  type        = "String"
  value       = aws_wafv2_web_acl.service_alb.arn

  tags = {
    ManagedBy = "terraform"
  }
}

output "service_alb_waf_acl_arn" {
  description = "REGIONAL WAF web ACL ARN — frontend ingress의 wafv2-acl-arn 어노테이션에 주입"
  value       = aws_wafv2_web_acl.service_alb.arn
}
