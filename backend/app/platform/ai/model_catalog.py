"""The one place a Claude model id literal is allowed to live in this codebase --
backend/tests/test_no_hardcoded_tenant_values.py's own model_id pattern explicitly excludes
this exact path (docs/HRMS_COMPLETE_SPEC.txt Part 1 Step 3). Every backend/app/ai_services/
*.py MODEL constant and platform/settings/bootstrap_definitions.py's ai.models.* defaults
import from here instead of writing the literal themselves.

Part 3's LLM gateway replaces this whole file: model choice becomes a per-tenant setting
resolved through ai.gateway.complete(purpose=...), routed to a connection (so a tenant can
bring their own key/model) rather than a fixed constant baked into the image. Until then,
this is the single source of truth every current call site and the Settings Registry's own
defaults both point at, so a model bump is a one-line, one-file change.
"""

CLAUDE_SONNET_5 = "claude-sonnet-5"
CLAUDE_HAIKU_4_5 = "claude-haiku-4-5"

# Current default model per ai_services purpose -- matches exactly what each
# backend/app/ai_services/*.py file hardcoded before this file existed (see
# docs/hardcode_inventory.md's model-id offender group).
RESUME_EXTRACTION = CLAUDE_HAIKU_4_5
RESUME_MATCHING = CLAUDE_HAIKU_4_5
CANDIDATE_RANKING = CLAUDE_SONNET_5
SHORTLIST_FEEDBACK = CLAUDE_HAIKU_4_5
INTERVIEW_QUESTIONS = CLAUDE_HAIKU_4_5
DOCUMENT_VALIDATION = CLAUDE_HAIKU_4_5
OFFER_LETTER_GENERATION = CLAUDE_HAIKU_4_5
JD_GENERATION = CLAUDE_SONNET_5
