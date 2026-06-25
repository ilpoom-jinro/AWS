output "api_anomaly_alert_sns_topic_arn" {
  description = "api-anomaly-alert SNS 토픽 ARN — Slack 담당자가 구독 추가 시 참조"
  value       = aws_sns_topic.api_anomaly_alert.arn
}
