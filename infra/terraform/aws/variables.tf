# One module run = one client installation (docs/HRMS_COMPLETE_SPEC.txt Part 13 A, decision A1).

variable "client_slug" {
  description = "Short id for the client installation (names every resource)."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.client_slug))
    error_message = "lowercase letters, digits, hyphens; 2-31 chars."
  }
}

variable "environment" {
  description = "dev | uat | prod -- config is promoted between them with hrctl config-pack, never re-typed."
  type        = string
  validation {
    condition     = contains(["dev", "uat", "prod"], var.environment)
    error_message = "environment is dev, uat or prod."
  }
}

variable "region" {
  description = "Primary region. India only (data residency)."
  type        = string
  default     = "ap-south-1"
  validation {
    condition     = contains(["ap-south-1", "ap-south-2"], var.region)
    error_message = "Data residency: region must be ap-south-1 (Mumbai) or ap-south-2 (Hyderabad)."
  }
}

variable "dr_enabled" {
  description = "Cross-region DR: RDS automated-backup replication + S3 replication to dr_region."
  type        = bool
  default     = false
}

variable "dr_region" {
  type    = string
  default = "ap-south-2"
  validation {
    condition     = contains(["ap-south-1", "ap-south-2"], var.dr_region)
    error_message = "DR must also stay in India."
  }
}

variable "hosted_zone_name" {
  description = "Our Route53 zone the client subdomain lives under (e.g. hrms.example)."
  type        = string
}

variable "app_subdomain" {
  description = "Client subdomain under hosted_zone_name (e.g. clientname -> clientname.hrms.example)."
  type        = string
}

variable "custom_domains" {
  description = "Client-owned domains (CNAME to CloudFront + ACM validation records added on their side)."
  type        = list(string)
  default     = []
}

variable "backend_image" { type = string }
variable "frontend_image_bucket_prefix" {
  type    = string
  default = "app"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "db_allocated_storage_gb" {
  type    = number
  default = 50
}

variable "backup_retention_days" {
  description = "RDS automated backups + PITR window."
  type        = number
  default     = 14
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.small"
}

variable "api_desired_count" {
  type    = number
  default = 2
}

variable "worker_desired_count" {
  type    = number
  default = 1
}

variable "alarm_email" {
  description = "Where CloudWatch alarms go (an ops mailbox, not client data)."
  type        = string
}
