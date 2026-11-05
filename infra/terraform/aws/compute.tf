# ---------------- ECS Fargate: api / worker / beat ----------------

resource "aws_ecs_cluster" "this" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/hrms/${local.name}"
  retention_in_days = var.environment == "prod" ? 365 : 30
  kms_key_id        = aws_kms_key.data.arn
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.app.arn] },
      { Effect = "Allow", Action = ["kms:Decrypt"], Resource = [aws_kms_key.data.arn] },
    ]
  })
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task_s3" {
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"], Resource = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"] },
      { Effect = "Allow", Action = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"], Resource = [aws_kms_key.data.arn] },
    ]
  })
}

locals {
  secret_keys = ["DATABASE_URL", "CONTROL_PLANE_DATABASE_URL", "APP_DATABASE_URL", "APP_CONTROL_PLANE_DATABASE_URL", "REDIS_URL", "SECRET_KEY", "MASTER_KEY"]
  common_env = [
    { name = "TENANCY_MODE", value = "single" },
    { name = "CELERY_ALWAYS_EAGER", value = "false" },
    { name = "LOG_FORMAT", value = "json" },
    { name = "HSTS_ENABLED", value = "true" },
    { name = "ALLOWED_REGIONS", value = var.dr_enabled ? "${var.region},${var.dr_region}" : var.region },
    { name = "FRONTEND_URL", value = "https://${local.app_host}" },
    { name = "APP_BASE_URL", value = "https://${local.app_host}/_api" },
    { name = "CORS_ORIGINS", value = join(",", concat(["https://${local.app_host}"], [for d in var.custom_domains : "https://${d}"])) },
  ]
  secrets = [for k in local.secret_keys : { name = k, valueFrom = "${aws_secretsmanager_secret.app.arn}:${k}::" }]
  roles = {
    api    = { command = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"], cpu = 512, memory = 1024, count = var.api_desired_count, port = true }
    worker = { command = ["celery", "-A", "app.platform.jobs.scheduled:celery_app", "worker", "-Q", "high,default,low", "--concurrency", "4"], cpu = 512, memory = 1024, count = var.worker_desired_count, port = false }
    beat   = { command = ["celery", "-A", "app.platform.jobs.scheduled:celery_app", "beat", "--schedule", "/tmp/celerybeat-schedule"], cpu = 256, memory = 512, count = 1, port = false }
  }
}

resource "aws_ecs_task_definition" "role" {
  for_each                 = local.roles
  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name         = each.key
    image        = var.backend_image
    command      = each.value.command
    essential    = true
    environment  = local.common_env
    secrets      = local.secrets
    portMappings = each.value.port ? [{ containerPort = 8000 }] : []
    logConfiguration = {
      logDriver = "awslogs"
      options   = { awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.region, awslogs-stream-prefix = each.key }
    }
  }])
}

resource "aws_ecs_task_definition" "migrate" {
  family                   = "${local.name}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name        = "migrate"
    image       = var.backend_image
    command     = ["sh", "-c", "python -m hrctl.installation init && python -m hrctl.migrate --all-tenants --control-plane"]
    essential   = true
    environment = local.common_env
    secrets     = local.secrets
    logConfiguration = {
      logDriver = "awslogs"
      options   = { awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.region, awslogs-stream-prefix = "migrate" }
    }
  }])
}

resource "aws_ecs_service" "role" {
  for_each        = local.roles
  name            = each.key
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.role[each.key].arn
  desired_count   = each.value.count
  launch_type     = "FARGATE"
  # beat must never run twice (would double-fire schedules)
  deployment_maximum_percent         = each.key == "beat" ? 100 : 200
  deployment_minimum_healthy_percent = each.key == "beat" ? 0 : 100
  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.app.id]
  }
  dynamic "load_balancer" {
    for_each = each.value.port ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.api.arn
      container_name   = each.key
      container_port   = 8000
    }
  }
}

# ---------------- ALB for the API ----------------

resource "aws_lb" "api" {
  name               = substr(replace(local.name, "_", "-"), 0, 32)
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "api" {
  name        = substr("${replace(local.name, "_", "-")}-api", 0, 32)
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.this.id
  target_type = "ip"
  health_check {
    path    = "/readyz"
    matcher = "200"
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.api.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
