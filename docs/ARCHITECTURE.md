# HR Automation MVP — Architecture, Database Schema & AI Prompt Design

**Scope:** Single-tenant MVP for Indusind. 13-step lifecycle, 10 modules, 7 GenAI services.
**Purpose of this doc:** Give Claude Code (and you) a shared starting context. Paste this into your repo as `docs/ARCHITECTURE.md` and reference it when starting new Claude Code sessions.

---

## 1. High-Level Architecture

```
                         ┌─────────────────────────┐
                         │   React + MUI Frontend    │
                         │  (Recruitment Dashboard)  │
                         └────────────┬─────────────┘
                                      │ REST (JSON)
                         ┌────────────▼─────────────┐
                         │   FastAPI Monolith        │
                         │  (modular internally)      │
                         │                            │
                         │  /jobs      /candidates    │
                         │  /screening /interviews    │
                         │  /salary    /bgv           │
                         │  /offers    /reports        │
                         │  /auth      /audit          │
                         └───┬─────────────────┬──────┘
                             │                 │
                  ┌──────────▼──────┐   ┌──────▼───────────┐
                  │   PostgreSQL      │   │  Claude API        │
                  │  (single tenant)  │   │  (7 AI services)   │
                  └──────────────────┘   └────────────────────┘
                             │
                  ┌──────────▼──────┐
                  │  S3 (or local     │
                  │  disk for MVP)    │
                  │  Resumes, BGV docs│
                  └───────────────────┘

  External integrations (called directly from FastAPI, no message bus yet):
  Career Portal / one job board · Google Calendar · Email (SMTP/SendGrid) · DocuSign
```

**Why a monolith, not microservices:** One deployable unit, one process to monitor, one CI/CD pipeline. Internally organized as modules (`app/jobs/`, `app/screening/`, `app/bgv/`, etc.) so it can be split into services later if a module needs independent scaling — but you won't manage 7 deployments solo.

**Why no Kafka/Elasticsearch yet:** At ~150 requisitions/~400-12,000 applications a month (whichever volume gets confirmed), Postgres + FastAPI background tasks handle this fine. Revisit only if query latency or async fan-out actually becomes a bottleneck.

---

## 2. Repo Structure

```
hr-automation/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/            # config, security, db session
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/          # Pydantic schemas
│   │   ├── jobs/              # JD Management + Job Posting
│   │   ├── candidates/        # Resume Collection
│   │   ├── screening/         # AI Screening + Candidate Ranking
│   │   ├── shortlisting/      # HR Shortlisting
│   │   ├── scheduling/        # Interview Scheduling + Feedback
│   │   ├── salary/            # Salary Validation + Approval
│   │   ├── bgv/                # BGV Request/Collection/Verification
│   │   ├── offers/             # Offer & Onboarding
│   │   ├── reports/            # Reports & Status
│   │   ├── audit/              # Audit logging middleware
│   │   ├── ai_services/        # Claude API wrappers, one file per service
│   │   └── integrations/       # Calendar, DocuSign, email, job board
│   ├── alembic/                # DB migrations
│   ├── tests/
│   └── requirements.txt
├── frontend/                    # Vite + React + TypeScript + MUI, scaffolded
│   └── src/
│       ├── api/                # typed fetch client (client.ts, types.ts) against backend
│       ├── layout/              # sidebar + main content shell (AppLayout.tsx)
│       └── pages/                # one page per module; Jobs is functional, rest are placeholders
└── docs/
    ├── ARCHITECTURE.md          # this file
    └── PROMPTS.md                # AI service prompt library
```

**Frontend status:** scaffolded and running (`npm run dev` at `frontend/`, port 5173) against the
backend at `http://localhost:8000` (no auth yet, CORS enabled for the dev origin in
`backend/app/main.py`). Jobs page is fully wired to `/jobs` (list, create, generate-jd); the other
nine module pages are "Coming soon" placeholders pending their own build-out.

**Local dev database:** no `docker-compose.yml` — Docker isn't installed in this dev environment. Local dev runs against a native Windows PostgreSQL service (`postgresql-x64-17`) listening on `localhost:5432`, configured via `backend/.env`'s `DATABASE_URL`. Revisit a compose file if dev moves to a machine where Docker is the natural fit, or once there's a second service (e.g. the frontend) to orchestrate alongside it.

---

## 3. Database Schema (MVP, single-tenant — no `tenant_id` columns needed yet)

```sql
-- Users & roles
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(50) NOT NULL CHECK (role IN ('recruiter','hiring_manager','interviewer','admin')),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Job requisitions / JDs
CREATE TABLE job_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    department VARCHAR(255),
    location VARCHAR(255),
    experience_level VARCHAR(100),
    skills JSONB,                      -- structured skill list
    salary_band_min NUMERIC,
    salary_band_max NUMERIC,
    hiring_manager_id UUID REFERENCES users(id),
    positions_count INT DEFAULT 1,
    jd_text TEXT,                      -- GenAI-drafted JD
    status VARCHAR(50) DEFAULT 'draft' -- draft, ready_for_publishing, published, closed
        CHECK (status IN ('draft','ready_for_publishing','published','closed')),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Candidates & applications
CREATE TABLE candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    resume_path TEXT,                  -- S3 key or local path
    parsed_fields JSONB,                -- Resume Parser output
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_role_id UUID REFERENCES job_roles(id),
    candidate_id UUID REFERENCES candidates(id),
    match_score NUMERIC,                -- Resume Matcher output
    skill_match_pct NUMERIC,
    missing_skills JSONB,
    ranking_rationale TEXT,             -- Candidate Ranking explainability
    status VARCHAR(50) DEFAULT 'received'
        CHECK (status IN (
          'received','screened','hr_selected','hr_rejected',
          'interview_scheduled','interview_selected','interview_rejected',
          'salary_ok','salary_above_band','salary_approved','salary_rejected',
          'bgv_requested','bgv_pending','bgv_cleared','bgv_rejected',
          'offer_sent','onboarding_started','onboarding_completed'
        )),
    expected_salary NUMERIC,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Interviews
CREATE TABLE interviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID REFERENCES applications(id),
    interviewer_id UUID REFERENCES users(id),
    scheduled_at TIMESTAMPTZ,
    meeting_link TEXT,
    technical_rating INT,
    communication_rating INT,
    overall_rating INT,
    comments TEXT,
    decision VARCHAR(20) CHECK (decision IN ('selected','rejected', NULL)),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- BGV documents
CREATE TABLE bgv_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID REFERENCES applications(id),
    doc_type VARCHAR(50) CHECK (doc_type IN ('aadhaar','pan','degree','experience')),
    file_path TEXT,
    validation_status VARCHAR(50) DEFAULT 'pending'
        CHECK (validation_status IN ('pending','valid','invalid','needs_review')),
    validator_output JSONB,             -- Document Validator OCR/classification result
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Offers
CREATE TABLE offers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID REFERENCES applications(id),
    offer_letter_text TEXT,             -- Offer Letter Generator output
    docusign_envelope_id VARCHAR(255),
    signed BOOLEAN DEFAULT false,
    onboarding_status VARCHAR(50) DEFAULT 'not_started'
        CHECK (onboarding_status IN ('not_started','in_progress','completed')),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Audit log — every AI action, score, and status transition
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(50),            -- 'application', 'job_role', etc.
    entity_id UUID,
    action VARCHAR(100),                -- 'ai_screening_scored', 'status_changed', 'hr_override'
    actor VARCHAR(50),                  -- 'system' or user id
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

**Notes:**
- `status` on `applications` is intentionally one flat enum spanning the whole lifecycle rather than a state-machine table — simpler for a solo build; add a proper workflow-engine table only if you find yourself needing configurable transitions.
- Every write to `applications.status`, every AI score, and every HR override should also insert into `audit_log` — build this as a small helper function/decorator, not scattered manual calls.
- Adding multi-tenancy later means adding a `tenant_id` column to every table above and a Postgres row-level-security policy — schema is written now so that migration is additive, not a rewrite.

---

## 4. AI Prompt Design — Approach for the 7 Services

General principles applied to all seven services below:
- **Structured output.** Every service should return JSON (never prose) so the backend can parse deterministically. Use a system prompt that says "respond only with valid JSON matching this schema" plus the schema itself.
- **Advisory only.** Every prompt should produce a score/recommendation + rationale, never an auto-decision. HR/interviewer makes the final call, per the proposal's human-in-the-loop principle.
- **Model choice:** Haiku for high-volume/low-complexity (Resume Parser, first-pass Matcher, Interview Questions, Document Validator, Offer Letter); Sonnet for judgment-heavy (JD Generator, Candidate Ranking's detailed shortlist scoring).

### Example: JD Generator (Claude Sonnet)

```
System: You are an HR job-description writer. Given structured role inputs,
produce a complete, professional job description. Respond only with valid JSON:
{"title": string, "summary": string, "responsibilities": [string],
 "required_skills": [string], "nice_to_have": [string], "experience_required": string}
No text outside the JSON.

User: Role inputs:
{title}, {department}, {location}, {experience_level}, {skills}, {salary_band}
```

### Example: Resume Matcher (Claude Haiku, post embedding pre-filter)

```
System: You compare a candidate resume against a job description. Respond only
with valid JSON:
{"match_score": 0-100, "skill_match_pct": 0-100,
 "missing_skills": [string], "recommendation": "strong_fit"|"possible_fit"|"weak_fit"}
Base this strictly on evidence in the resume text. Do not infer skills not stated or clearly implied.

User: JD: {jd_text}
Resume: {parsed_resume_text}
```

The remaining five services (Resume Parser, Candidate Ranking, Interview Question Generator, Document Validator, Offer Letter Generator) follow the same pattern — a fixed JSON schema, a narrow single-purpose instruction, explicit "don't infer beyond evidence" guardrails where the output affects a candidate's outcome. I can draft the full prompt for any of these on request — happy to do the rest now, or as you reach each module.

---

## 5. How to hand this off to Claude Code

1. Save this file as `docs/ARCHITECTURE.md` in your repo.
2. Start your Claude Code session with something like: *"Read docs/ARCHITECTURE.md, then scaffold the FastAPI backend structure and the initial Alembic migration for the schema in Section 3."*
3. When you hit a design question mid-build (e.g., "should salary approval be its own table?") or a bug you're stuck on, bring it back here — paste the error or the relevant code and I'll help you reason through it.
4. When you're ready for the next AI service prompt (Resume Parser, Candidate Ranking, etc.), just ask and I'll draft it in the same structured-JSON style.
