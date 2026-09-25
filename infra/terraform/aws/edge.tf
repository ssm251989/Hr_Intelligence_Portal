# ---------------- DNS + certificates + CloudFront ----------------
# CloudFront serves the SPA from S3 and forwards /_api/* to the ALB with the viewer Host
# header preserved (the tenant is resolved from Host).

data "aws_route53_zone" "this" { name = var.hosted_zone_name }

locals { api_origin_host = "origin-${local.app_host}" }

resource "aws_acm_certificate" "api" {
  domain_name       = local.api_origin_host
  validation_method = "DNS"
}

resource "aws_route53_record" "api_validation" {
  for_each = { for o in aws_acm_certificate.api.domain_validation_options : o.domain_name => o }
  zone_id  = data.aws_route53_zone.this.zone_id
  name     = each.value.resource_record_name
  type     = each.value.resource_record_type
  records  = [each.value.resource_record_value]
  ttl      = 300
}

resource "aws_acm_certificate_validation" "api" {
  certificate_arn         = aws_acm_certificate.api.arn
  validation_record_fqdns = [for r in aws_route53_record.api_validation : r.fqdn]
}

resource "aws_route53_record" "api_origin" {
  zone_id = data.aws_route53_zone.this.zone_id
  name    = local.api_origin_host
  type    = "A"
  alias {
    name                   = aws_lb.api.dns_name
    zone_id                = aws_lb.api.zone_id
    evaluate_target_health = true
  }
}

resource "aws_acm_certificate" "web" {
  provider                  = aws.us_east_1
  domain_name               = local.app_host
  subject_alternative_names = var.custom_domains
  validation_method         = "DNS"
}

resource "aws_route53_record" "web_validation" {
  # Only our own zone's names can be validated here; custom-domain validation records are
  # handed to the client (see outputs.custom_domain_validation).
  for_each = { for o in aws_acm_certificate.web.domain_validation_options : o.domain_name => o if endswith(o.domain_name, var.hosted_zone_name) }
  zone_id  = data.aws_route53_zone.this.zone_id
  name     = each.value.resource_record_name
  type     = each.value.resource_record_type
  records  = [each.value.resource_record_value]
  ttl      = 300
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = local.name
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.web.arn } }
    }]
  })
}

data "aws_cloudfront_cache_policy" "disabled" { name = "Managed-CachingDisabled" }
data "aws_cloudfront_cache_policy" "optimized" { name = "Managed-CachingOptimized" }
data "aws_cloudfront_origin_request_policy" "all_viewer" { name = "Managed-AllViewer" }
data "aws_cloudfront_response_headers_policy" "security" { name = "Managed-SecurityHeadersPolicy" }

resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  aliases             = concat([local.app_host], var.custom_domains)
  default_root_object = "index.html"
  price_class         = "PriceClass_200" # includes India edge locations

  origin {
    origin_id                = "web"
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_path              = "/${var.frontend_image_bucket_prefix}"
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  origin {
    origin_id   = "api"
    domain_name = local.api_origin_host
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id           = "web"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security.id
  }

  ordered_cache_behavior {
    path_pattern             = "/_api/*"
    target_origin_id         = "api"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id # forwards Host
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.strip_api_prefix.arn
    }
  }

  # SPA routes -> index.html
  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate.web.arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

resource "aws_cloudfront_function" "strip_api_prefix" {
  name    = "${local.name}-strip-api"
  runtime = "cloudfront-js-2.0"
  code    = "function handler(event) { var r = event.request; r.uri = r.uri.replace(/^\\/_api/, '') || '/'; return r; }"
}

resource "aws_route53_record" "web" {
  zone_id = data.aws_route53_zone.this.zone_id
  name    = local.app_host
  type    = "A"
  alias {
    name                   = aws_cloudfront_distribution.web.domain_name
    zone_id                = aws_cloudfront_distribution.web.hosted_zone_id
    evaluate_target_health = false
  }
}
