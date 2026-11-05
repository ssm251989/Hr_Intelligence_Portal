# Example only -- copy per client/environment (e.g. clients/<slug>/prod.tfvars), keep out of git
# if it names a real client. No secrets belong in tfvars.
client_slug      = "democlient"
environment      = "uat"
region           = "ap-south-1"
dr_enabled       = false
hosted_zone_name = "hrms.example"
app_subdomain    = "democlient-uat"
custom_domains   = []
backend_image    = "ghcr.io/example/hrms-backend:0.13.0"
alarm_email      = "ops@hrms.example"
