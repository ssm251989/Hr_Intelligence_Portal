{{- define "hrms.name" -}}{{ .Release.Name }}{{- end -}}

{{- define "hrms.labels" -}}
app.kubernetes.io/name: hrms
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "hrms.backendImage" -}}{{ .Values.image.backend.repository }}:{{ default .Chart.AppVersion .Values.image.backend.tag }}{{- end -}}
{{- define "hrms.frontendImage" -}}{{ .Values.image.frontend.repository }}:{{ default .Chart.AppVersion .Values.image.frontend.tag }}{{- end -}}

{{/* Env shared by api / worker / beat / migration job. */}}
{{- define "hrms.backendEnv" -}}
- name: TENANCY_MODE
  value: {{ .Values.tenancyMode | quote }}
- name: SECRET_BACKEND
  value: {{ .Values.secretBackend | quote }}
- name: REDIS_URL
  value: {{ .Values.external.redisUrl | quote }}
- name: CELERY_ALWAYS_EAGER
  value: "false"
- name: FRONTEND_URL
  value: {{ .Values.config.frontendUrl | quote }}
- name: APP_BASE_URL
  value: {{ .Values.config.appBaseUrl | quote }}
- name: CORS_ORIGINS
  value: {{ .Values.config.corsOrigins | quote }}
- name: ALLOWED_REGIONS
  value: {{ .Values.config.allowedRegions | quote }}
- name: LOG_FORMAT
  value: {{ .Values.config.logFormat | quote }}
- name: HSTS_ENABLED
  value: {{ .Values.config.hstsEnabled | quote }}
- name: CLAMAV_HOST
  value: {{ .Values.config.clamavHost | quote }}
- name: AV_SCAN_REQUIRED
  value: {{ .Values.config.avScanRequired | quote }}
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ .Values.config.otelEndpoint | quote }}
- name: RATE_LIMIT_USER_PER_MINUTE
  value: {{ .Values.config.rateLimitUserPerMinute | quote }}
- name: RATE_LIMIT_ANON_PER_MINUTE
  value: {{ .Values.config.rateLimitAnonPerMinute | quote }}
- name: RATE_LIMIT_TENANT_PER_MINUTE
  value: {{ .Values.config.rateLimitTenantPerMinute | quote }}
- name: TENANT_MAX_CONCURRENT_JOBS
  value: {{ .Values.worker.tenantMaxConcurrentJobs | quote }}
{{- end -}}
