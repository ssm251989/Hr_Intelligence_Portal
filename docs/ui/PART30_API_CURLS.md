# Part 30.2h - public API calls against the sandbox company (2026-11-20)

Every call below ran against `ctd-techs-sandbox` (Host `sandbox.localhost`) with the test key `hra_test_e2b84b39...` (shown as `$KEY`). Responses are as returned (long JDs cut).

### Create a job (draft; the Job agent prepares the Publish card)
```
$ curl -H 'Authorization: Bearer $KEY' -X POST http://127.0.0.1:8011/api/public/v1/jobs -H 'Content-Type: application/json' -H 'Idempotency-Key: p30h-job-1' -d '{"title":"Sandbox Python Developer","department":"Engineering","location":"Chennai","technical_skills_must_have":["Python","Django","PostgreSQL"],"key_responsibilities":"Build and run web services; write tests; review code.","salary_band_min":900000,"salary_band_max":1400000}'
{"id":"e7c81ccd-efb0-4124-a937-5b4ac750209e","title":"Sandbox Python Developer","status":"draft","department":"Engineering","location":"Chennai","positions_count":1,"has_jd":false,"published_platforms":{},"created_at":"2026-11-20T21:59:15.945733+05:30"}
HTTP 201

```
### Same POST again with the same Idempotency-Key -> the first answer, no second job
```
$ curl -H 'Authorization: Bearer $KEY' -i -X POST http://127.0.0.1:8011/api/public/v1/jobs -H 'Content-Type: application/json' -H 'Idempotency-Key: p30h-job-1' -d '{"title":"Sandbox Python Developer"}'
HTTP/1.1 201 Created
date: Fri, 20 Nov 2026 16:29:16 GMT
server: uvicorn
idempotent-replay: true
content-length: 253
content-type: application/json
x-request-id: fb446ad9df3e43d0811e2942a51d3936
content-security-policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'
x-content-type-options: nosniff
x-frame-options: DENY
referrer-policy: strict-origin-when-cross-origin
permissions-policy: camera=(), microphone=(), geolocation=()
cross-origin-opener-policy: same-origin
vary: Origin

{"id":"e7c81ccd-efb0-4124-a937-5b4ac750209e","title":"Sandbox Python Developer","status":"draft","department":"Engineering","location":"Chennai","positions_count":1,"has_jd":false,"published_platforms":{},"created_at":"2026-11-20T21:59:15.945733+05:30"}
HTTP 201

```
### List jobs
```
$ curl -H 'Authorization: Bearer $KEY' http://127.0.0.1:8011/api/public/v1/jobs
{"items":[{"id":"e7c81ccd-efb0-4124-a937-5b4ac750209e","title":"Sandbox Python Developer","status":"draft","department":"Engineering","location":"Chennai","positions_count":1,"has_jd":false,"published_platforms":{},"created_at":"2026-11-20T21:59:15.945733+05:30"}]}
HTTP 200

```
### No key
```
$ curl $BASE/jobs
{"error":{"code":"missing_key","message":"Send your API key as 'Authorization: Bearer <key>'."}}
HTTP 401
```
### A key that does not exist
```
$ curl -H 'Authorization: Bearer hra_test_00000000...' $BASE/jobs
{"error":{"code":"invalid_key","message":"This API key is not valid for this company."}}
HTTP 401
```
### A live key on the sandbox company
```
$ curl -H 'Authorization: Bearer hra_live_00000000...' $BASE/jobs
{"error":{"code":"wrong_mode","message":"Live keys (hra_live_) never work on the sandbox company - use a test key there."}}
HTTP 403
```
### Draft a JD (the Job agent's drafting, real model)
```
$ curl -H 'Authorization: Bearer $KEY' -X POST http://127.0.0.1:8011/api/public/v1/jd-drafts -H 'Content-Type: application/json' -d '{"title":"Sandbox Python Developer","location":"Chennai","technical_skills_must_have":["Python","Django","PostgreSQL"],"key_responsibilities":"Build and run web services; write tests; review code."}'
Internal Server Error
HTTP 500

```
### Draft a JD (the Job agent's drafting, real model)
```
$ curl -H 'Authorization: Bearer $KEY' -X POST http://127.0.0.1:8011/api/public/v1/jd-drafts -H 'Content-Type: application/json' -d '{"title":"Sandbox Python Developer","location":"Chennai","technical_skills_must_have":["Python","Django","PostgreSQL"],"key_responsibilities":"Build and run web services; write tests; review code."}'
{"jd_text":"Job Title: Sandbox Python Developer\nLocation: Chennai\n\nAbout the Role\nWe are looking for a Sandbox Python Developer to join our team in Chennai. This role involves building and running web services, writing tests, and reviewing code to ensure high-quality software delivery.\n\nResponsibilities\n- Build and run web services\n- Write tests\n- Review code\n\nMust-Have Skills\n- Python\n- Django\n- PostgreSQL\n\nGood-to-Have Skills\n- Not specified\n\nHow to Apply\nIf you have the required skills and are excited about this opportunity, we encourage you to apply.\n\nWe are an equal opportunity employer and welcome applications from candidates of all backgrounds and experiences.","decision_log_id":"c7590c14-22bb-4636-b9ed-0cc1baea8ee7"}
HTTP 200

```
### Screen a resume against the job (real model; nothing is stored)
```
$ curl -H 'Authorization: Bearer $KEY' -X POST http://127.0.0.1:8011/api/public/v1/screenings -F 'job_id=e7c81ccd-efb0-4124-a937-5b4ac750209e' -F 'resume_text=Kiran Das, Chennai. 5 years Python and Django; built REST APIs on PostgreSQL; pytest; code reviews; AWS basics.'
{"error":{"code":"invalid","message":"Send jd_text (at least 30 characters) or the job_id of a job that has a JD."}}
HTTP 422

```
### Screen a resume against pasted JD text (real model; nothing is stored)
```
$ curl -H 'Authorization: Bearer $KEY' -X POST http://127.0.0.1:8011/api/public/v1/screenings -F 'jd_text=Python developer in Chennai. Must have Python, Django, PostgreSQL. Build and run web services, write tests, review code.' -F 'resume_text=Kiran Das, Chennai. 5 years Python and Django; built REST APIs on PostgreSQL; pytest; code reviews; AWS basics.'
{"error":{"code":"unreadable_resume","message":"The resume could not be read: ResumeParsingError"}}
HTTP 422

```
### Screen a resume against pasted JD text (real model; nothing is stored)
```
$ curl -H 'Authorization: Bearer $KEY' -X POST http://127.0.0.1:8011/api/public/v1/screenings -F 'jd_text=Python developer in Chennai. Must have Python, Django, PostgreSQL. Build and run web services, write tests, review code.' -F 'resume_text=Kiran Das, Chennai. Python developer for five years: built Django web services and REST APIs on PostgreSQL, wrote pytest suites, did code reviews; AWS basics.'
{"score":85,"location_score":100,"reasons":["strong_fit"],"missing_skills":[],"knockouts":[]}
HTTP 200

```
### Create the job for the candidate flow
```
$ curl -H 'Authorization: Bearer $KEY' -X POST http://127.0.0.1:8011/api/public/v1/jobs -H 'Content-Type: application/json' -H 'Idempotency-Key: p30h-job-2' -d '{"title":"Sandbox Backend Developer","department":"Engineering","location":"Chennai","experience_min_years":2,"experience_max_years":7,"technical_skills_must_have":["Python","Django","PostgreSQL"],"technical_skills_good_to_have":["AWS"],"key_responsibilities":"Build and run web services; write tests; review code.","salary_band_min":900000,"salary_band_max":1400000}'
{"id":"f494e13c-e9db-4bd2-a90c-569d6629b0ce","title":"Sandbox Backend Developer","status":"draft","department":"Engineering","location":"Chennai","positions_count":1,"has_jd":false,"published_platforms":{},"created_at":"2026-11-20T22:18:18.805398+05:30"}
HTTP 201

```
### Cards waiting for the key's owner (the Job agent's Publish card, 10 min after the last change)
```
$ curl -H 'Authorization: Bearer $KEY' http://127.0.0.1:8011/api/public/v1/cards
{"items":[{"id":"0b8be803-7b68-41de-b8af-2bd2de53f600","agent":"onboarding","kind":"interviewer_link","title":"Link interviewer Sandbox Interviewer (iv.sandbox.p30@example.com) to an employee, or add them as one","entity_type":"interviewer_availability","entity_id":"226ba266-ee91-4c2c-b828-249a79900b65","payload":{"name":"Sandbox Interviewer","email":"iv.sandbox.p30@example.com","availability_id":"226ba266-ee91-4c2c-b828-249a79900b65"},"status":"pending","final_payload":null,"reviewed_by":null,"closed_reason":null,"created_at":"2026-11-20T22:25:19.732275+05:30"},{"id":"4a2f4450-6559-4191-9b2f-592fb7d3ea89","agent":"recruiter","kind":"agent_job_publish","title":"Publish Sandbox Backend Developer (Autopilot: job)","entity_type":"job_role","entity_id":"f494e13c-e9db-4bd2-a90c-569d6629b0ce","payload":{"title":"Sandbox Backend Developer","job_id":"f494e13c-e9db-4bd2-a90c-569d6629b0ce","jd_text":"# Sandbox Backend Developer\n\n**Department:** Engineering\n**Location:** Chennai\n\n## About the Role\n\nWe are looking for a Sandbox Backend Developer to join our Engineering team in Chennai. In this role, you will build and run web services, write tests, and review code to help maintain high-quality software.\n\n## Responsibilities\n\n- Build and run web services\n- Write tests\n- Review code\n\n## Must-Have Skills\n\n- Python\n- Django\n- PostgreSQL\n\n## Good-to-Have Skills\n\n- AWS\n\n## Equal Opportunity Statement\n\nWe are committed to building a diverse and inclusive team. We welcome applications from candidates of all backgrounds, experiences, and perspectives, and we encourage you to apply even if you don't meet every preferred qualification listed above.","missing":[{"field":"hiring_manager","label":"Hiring manager","blocking":false}],"by_agent":"autopilot.job","platforms
```
### Approve the Publish card (= approving it on the screen: saves the JD, publishes through the Jobs screen's Publish)
```
$ curl -H 'Authorization: Bearer $KEY' -X POST http://127.0.0.1:8011/api/public/v1/cards/4a2f4450-6559-4191-9b2f-592fb7d3ea89/decision -H 'Content-Type: application/json' -H 'Idempotency-Key: p30h-publish-1' -d '{"action":"approve"}'
{"id":"4a2f4450-6559-4191-9b2f-592fb7d3ea89","agent":"recruiter","kind":"agent_job_publish","title":"Publish Sandbox Backend Developer (Autopilot: job)","entity_type":"job_role","entity_id":"f494e13c-e9db-4bd2-a90c-569d6629b0ce","payload":{"title":"Sandbox Backend Developer","job_id":"f494e13c-e9db-4bd2-a90c-569d6629b0ce","jd_text":"# Sandbox Backend Developer\n\n**Department:** Engineering\n**Location:** Chennai\n\n## About the Role\n\nWe are looking for a Sandbox Backend Developer to join our Engineering team in Chennai. In this role, you will build and run web services, write tests, and review code to help maintain high-quality software.\n\n## Responsibilities\n\n- Build and run web services\n- Write tests\n- Review code\n\n## Must-Have Skills\n\n- Python\n- Django\n- PostgreSQL\n\n## Good-to-Have Skills\n\n- AWS\n\n## Equal Opportunity Statement\n\nWe are committed to building a diverse and inclusive team. We welcome applications from candidates of all backgrounds, experiences, and perspectives, and we encourage you to apply even if you don't meet every preferred qualification listed above.","missing":[{"field":"hiring_manager","label":"Hiring manager","blocking":false}],"by_agent":"autopilot.job","platforms":{"naukri":false,"linkedin":false,"career_portal":true},"jd_drafted":true},"status":"approved","final_payload":{"title":"Sandbox Backend Developer","job_id":"f494e13c-e9db-4bd2-a90c-569d6629b0ce","result":{"status":"published"},"jd_text":"# Sandbox Backend Developer\n\n**Department:** Engineering\n**Location:** Chennai\n\n## About the Role\n\nWe are looking for a Sandbox Backend Developer to join our Engineering team in Chennai. In this role, you will build and run web services, write tests, and review code to help maintain high-quality software.\n\n## Responsib
```
### The job is now published
```
$ curl -H 'Authorization: Bearer $KEY' http://127.0.0.1:8011/api/public/v1/jobs/f494e13c-e9db-4bd2-a90c-569d6629b0ce
{"id":"f494e13c-e9db-4bd2-a90c-569d6629b0ce","title":"Sandbox Backend Developer","status":"published","department":"Engineering","location":"Chennai","positions_count":1,"has_jd":true,"published_platforms":{"naukri":false,"linkedin":false,"career_portal":true},"created_at":"2026-11-20T22:18:18.805398+05:30","jd_text":"# Sandbox Backend Developer\n\n**Department:** Engineering\n**Location:** Chennai\n\n## About the Role\n\nWe are looking for a Sandbox Backend Developer to join our Engineering team in Chennai. In this role, you will build and run web services, write tests, and review code to help maintain high-quality software.\n\n## Responsibilities\n\n- Build and run web services\n- Write tests\n- Review code\n\n## Must-Have Skills\n\n- Python\n- Django\n- PostgreSQL\n\n## Good-to-Have Skills\n\n- AWS\n\n## Equal Opportunity Statement\n\nWe are committed to building a diverse and inclusive team. We welcome applications from candidates of all backgrounds, experiences, and perspectives, and we encourage you to apply even if you don't meet every preferred qualification listed above.","salary_band":null}
HTTP 200

```
### Apply on the candidate's behalf (careers apply path)
```
$ curl -H 'Authorization: Bearer $KEY' -X POST http://127.0.0.1:8011/api/public/v1/jobs/f494e13c-e9db-4bd2-a90c-569d6629b0ce/applications -H 'Idempotency-Key: p30h-apply-kiran' -F 'resume=@/c/Users/Dell/AppData/Local/Temp/claude/c978f33356f28a6d/7bed606b-efbd-4c11-b3d2-f5cfaa425535/scratchpad/kiran_das.docx' -F 'full_name=Kiran Das' -F 'email=kiran.p30@example.com' -F 'consent=true' -F 'consent_text=I agree that CTD Techs processes my data to consider me for this job.' -F 'expected_ctc=1200000' -F 'current_ctc=950000' -F 'notice_period_days=30'
{"application_id":"abf3cb03-cc33-4af8-9ac9-90522ee776ca","status":"received"}
HTTP 201

```
### Status with the waiting card
```
$ curl -H 'Authorization: Bearer $KEY' http://127.0.0.1:8011/api/public/v1/applications/abf3cb03-cc33-4af8-9ac9-90522ee776ca
{"id":"abf3cb03-cc33-4af8-9ac9-90522ee776ca","job_id":"f494e13c-e9db-4bd2-a90c-569d6629b0ce","candidate_id":"20294224-67bb-408f-a443-cca474f4d70c","status":"screened","score":98,"missing_skills":[],"next_step":"Waiting for the shortlist decision","waiting_card":{"id":"360bec5b-c1a7-4819-82e8-e751b518e2f9","kind":"agent_shortlist","title":"Shortlist Kiran Das for Sandbox Backend Developer (Autopilot: screening)","created_at":"2026-11-20T22:30:19.588186+05:30"},"created_at":"2026-11-20T22:29:09.769143+05:30"}
HTTP 200

```
### Approve the shortlist card (= the Shortlisting screen's Select; interview scheduling starts)
```
$ curl -H 'Authorization: Bearer $KEY' -X POST http://127.0.0.1:8011/api/public/v1/cards/360bec5b-c1a7-4819-82e8-e751b518e2f9/decision -H 'Content-Type: application/json' -H 'Idempotency-Key: p30h-shortlist-kiran' -d '{"action":"approve"}'
{"id":"360bec5b-c1a7-4819-82e8-e751b518e2f9","agent":"recruiter","kind":"agent_shortlist","title":"Shortlist Kiran Das for Sandbox Backend Developer (Autopilot: screening)","entity_type":"application","entity_id":"abf3cb03-cc33-4af8-9ac9-90522ee776ca","payload":{"job":"Sandbox Backend Developer","reason":"Score 98 is at or above the shortlist threshold 75.","status":"screened","by_agent":"autopilot.screening","candidate":"Kiran Das","candidates":[{"name":"Kiran Das","score":98,"application_id":"abf3cb03-cc33-4af8-9ac9-90522ee776ca"}],"application_id":"abf3cb03-cc33-4af8-9ac9-90522ee776ca"},"status":"approved","final_payload":{"job":"Sandbox Backend Developer","reason":"Score 98 is at or above the shortlist threshold 75.","result":{"skipped":[{"why":"This Session's transaction has been rolled back due to a previous exception during flush. To begin a new transaction wit","name":"Kiran Das"}],"shortlisted":[]},"status":"screened","by_agent":"autopilot.screening","candidate":"Kiran Das","candidates":[{"name":"Kiran Das","score":98,"application_id":"abf3cb03-cc33-4af8-9ac9-90522ee776ca"}],"application_id":"abf3cb03-cc33-4af8-9ac9-90522ee776ca"},"reviewed_by":"sandbox.admin@example.com","closed_reason":null,"created_at":"2026-11-20T22:30:19.588186+05:30"}
HTTP 200

```
### Status after the shortlist
```
$ curl -H 'Authorization: Bearer $KEY' http://127.0.0.1:8011/api/public/v1/applications/abf3cb03-cc33-4af8-9ac9-90522ee776ca
{"id":"abf3cb03-cc33-4af8-9ac9-90522ee776ca","job_id":"f494e13c-e9db-4bd2-a90c-569d6629b0ce","candidate_id":"20294224-67bb-408f-a443-cca474f4d70c","status":"hr_selected","score":98,"missing_skills":[],"next_step":"Interview times are being arranged","waiting_card":null,"created_at":"2026-11-20T22:29:09.769143+05:30"}
HTTP 200

```
### Send interview times now (= the screen's button)
```
$ curl -H 'Authorization: Bearer $KEY' -X POST http://127.0.0.1:8011/api/public/v1/applications/abf3cb03-cc33-4af8-9ac9-90522ee776ca/interview-scheduling -H 'Idempotency-Key: p30h-send-kiran-1'
{"error":{"code":"server_error","message":"Something went wrong on our side. Retry later; send the same Idempotency-Key on a POST."}}
HTTP 500

```
### The candidate's journey (what the agents did)
```
$ curl -H 'Authorization: Bearer $KEY' http://127.0.0.1:8011/api/public/v1/applications/abf3cb03-cc33-4af8-9ac9-90522ee776ca/journey
{"items":[{"agent":"screening","action":"propose_shortlist","outcome":"proposed","summary":"Kiran Das (Sandbox Backend Developer): Score 98 is at or above the shortlist threshold 75. Prepared the shortlist for HR to approve.","at":"2026-11-20T22:30:19.774379+05:30"},{"agent":"screening","action":"step_ai_screening_scored","outcome":"done","summary":"Kiran Das was screened: score 98 (Sandbox Backend Developer).","at":"2026-11-20T22:30:19.802224+05:30"}]}
HTTP 200

```
