output "app_url" { value = "https://${local.app_host}" }
output "api_origin" { value = "https://${local.api_origin_host}" }
output "cloudfront_domain" { value = aws_cloudfront_distribution.web.domain_name }
output "ecs_cluster" { value = aws_ecs_cluster.this.name }
output "migrate_task_definition" { value = aws_ecs_task_definition.migrate.arn }
output "app_secret_arn" { value = aws_secretsmanager_secret.app.arn }
output "data_bucket" { value = aws_s3_bucket.data.bucket }
output "frontend_bucket" { value = aws_s3_bucket.frontend.bucket }

output "custom_domain_validation" {
  description = "DNS records the client must add for each custom domain (ACM validation + CNAME to CloudFront)."
  value = {
    for o in aws_acm_certificate.web.domain_validation_options : o.domain_name => {
      validation = { name = o.resource_record_name, type = o.resource_record_type, value = o.resource_record_value }
      cname      = aws_cloudfront_distribution.web.domain_name
    } if !endswith(o.domain_name, var.hosted_zone_name)
  }
}
