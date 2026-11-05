# ---------------- RDS Postgres (tenant data + control plane on one instance, two DBs) ----------------

resource "random_password" "db_admin" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "this" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "this" {
  name   = local.name
  family = "postgres16"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }
}

resource "aws_db_instance" "this" {
  identifier                   = local.name
  engine                       = "postgres"
  engine_version               = "16"
  instance_class               = var.db_instance_class
  allocated_storage            = var.db_allocated_storage_gb
  max_allocated_storage        = var.db_allocated_storage_gb * 4
  storage_encrypted            = true
  kms_key_id                   = aws_kms_key.data.arn
  username                     = "hrms_admin"
  password                     = random_password.db_admin.result
  db_name                      = "hrms"
  db_subnet_group_name         = aws_db_subnet_group.this.name
  vpc_security_group_ids       = [aws_security_group.data.id]
  parameter_group_name         = aws_db_parameter_group.this.name
  multi_az                     = var.environment == "prod"
  backup_retention_period      = var.backup_retention_days # PITR window
  deletion_protection          = var.environment == "prod"
  skip_final_snapshot          = var.environment != "prod"
  final_snapshot_identifier    = var.environment == "prod" ? "${local.name}-final" : null
  performance_insights_enabled = true
  auto_minor_version_upgrade   = true
}

resource "aws_db_instance_automated_backups_replication" "dr" {
  count                  = var.dr_enabled ? 1 : 0
  provider               = aws.dr
  source_db_instance_arn = aws_db_instance.this.arn
  retention_period       = var.backup_retention_days
}

# ---------------- ElastiCache Redis ----------------

resource "aws_elasticache_subnet_group" "this" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "random_password" "redis" {
  length  = 32
  special = false
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id       = local.name
  description                = "${local.name} cache, locks, rate limits, Celery broker"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.redis_node_type
  num_cache_clusters         = var.environment == "prod" ? 2 : 1
  automatic_failover_enabled = var.environment == "prod"
  subnet_group_name          = aws_elasticache_subnet_group.this.name
  security_group_ids         = [aws_security_group.data.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis.result
  kms_key_id                 = aws_kms_key.data.arn
}

# ---------------- S3 (uploads/documents/exports; frontend) ----------------

resource "aws_s3_bucket" "data" {
  bucket = "${local.name}-data-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
  }
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket" "frontend" {
  bucket = "${local.name}-web-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------- Secrets Manager (app reads these as ECS secrets) ----------------

resource "random_password" "app_db" {
  length  = 32
  special = false
}

resource "random_password" "secret_key" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name       = "${local.name}/app"
  kms_key_id = aws_kms_key.data.arn
}

# MASTER_KEY is generated OUT OF BAND (a Fernet key) and put into this secret by the operator
# on first install -- Terraform state must never hold it. Placeholder value marks it unset.
resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DATABASE_URL                   = "postgresql://hrms_admin:${random_password.db_admin.result}@${aws_db_instance.this.address}:5432/hrms?sslmode=require"
    CONTROL_PLANE_DATABASE_URL     = "postgresql://hrms_admin:${random_password.db_admin.result}@${aws_db_instance.this.address}:5432/hrms_control_plane?sslmode=require"
    APP_DATABASE_URL               = "postgresql://hrms_app:${random_password.app_db.result}@${aws_db_instance.this.address}:5432/hrms?sslmode=require"
    APP_CONTROL_PLANE_DATABASE_URL = "postgresql://hrms_app:${random_password.app_db.result}@${aws_db_instance.this.address}:5432/hrms_control_plane?sslmode=require"
    REDIS_URL                      = "rediss://:${random_password.redis.result}@${aws_elasticache_replication_group.this.primary_endpoint_address}:6379/0"
    SECRET_KEY                     = random_password.secret_key.result
    MASTER_KEY                     = "SET-OUT-OF-BAND"
  })
  lifecycle { ignore_changes = [secret_string] }
}
