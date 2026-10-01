"""Friendly errors (docs/HRMS_COMPLETE_SPEC.txt Part 14 section 8): configuration problems
come back as `{"detail": {"code", "message", "fix", "fix_path"}}` with a 4xx status -- a
plain-language fix and a link to the right settings page -- and an unexpected failure is a
500 with a request id to quote, never a raw traceback.

Only exceptions that ESCAPE a router reach these handlers; routers that already map an
error to a specific HTTPException keep doing so.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


def _body(code: str, message: str, fix: str, fix_path: str) -> dict:
    return {"detail": {"code": code, "message": message, "fix": fix, "fix_path": fix_path}}


# exception class path -> (status, code, message, fix, fix_path)
_MAPPINGS = (
    ("app.platform.connectors.router.NoConnectionForPurposeError", 409, "NO_CONNECTION_FOR_PURPOSE",
     "This needs a connected account that isn't set up yet.", "Connect an account and route this purpose to it.", "/settings#connections"),
    ("app.platform.comms.templates.TemplateNotFoundError", 409, "TEMPLATE_NOT_PUBLISHED",
     "The message template for this step isn't published.", "Publish the template (or turn off the rule that uses it).", "/settings#communications"),
    ("app.platform.comms.renderer.TemplateRenderError", 409, "TEMPLATE_RENDER_FAILED",
     "A message template couldn't be filled in.", "Preview the template and fix the placeholder it names.", "/settings#communications"),
    ("app.recruitment.prompt_registry.PromptNotFoundError", 409, "PROMPT_NOT_PUBLISHED",
     "The AI prompt for this feature isn't published.", "Publish the prompt in the prompt registry.", "/settings#ai"),
    ("app.core_hr.letters.LetterTemplateNotFoundError", 409, "LETTER_TEMPLATE_MISSING",
     "The letter template for this step isn't published.", "Publish a letter template with this key.", "/settings#core-hr"),
    ("app.platform.metadata.sequences.SequenceNotFoundError", 409, "SEQUENCE_MISSING",
     "A numbering sequence this needs isn't defined.", "Define the sequence under Metadata.", "/settings#metadata"),
    ("app.platform.workflow.engine.WorkflowConfigError", 409, "WORKFLOW_CONFIG",
     "The approval workflow for this is misconfigured.", "Open the workflow, simulate it, fix the flagged step and republish.", "/settings#workflows"),
    ("app.platform.workflow.definitions.DefinitionNotFoundError", 409, "WORKFLOW_MISSING",
     "No published approval workflow exists for this.", "Publish the workflow.", "/settings#workflows"),
    ("app.platform.iam.authz.ScopeNotSupportedError", 409, "SCOPE_NOT_SUPPORTED",
     "Your role's data scope can't be applied to this list.", "Ask an admin to give this role an 'all' or supported scope.", "/settings#access"),
    ("app.platform.ai.governance.AIDisabledError", 403, "AI_DISABLED",
     "This AI feature is turned off for your organisation.", "An admin can turn it on under AI settings.", "/settings#ai"),
    ("app.platform.ai.governance.BudgetExceededError", 429, "AI_BUDGET_EXCEEDED",
     "This month's AI budget is used up.", "An admin can raise the budget under AI settings.", "/settings#ai"),
    ("app.platform.connectors.registry.NotYetImplementedProviderError", 409, "PROVIDER_NOT_AVAILABLE",
     "The connected provider isn't supported yet.", "Route this purpose to a supported provider.", "/settings#connections"),
    ("app.platform.ops.av_scan.UploadRejectedError", 400, "UPLOAD_REJECTED",
     "The file was rejected.", "Check the file and upload it again.", ""),
)


def _import(path: str):
    module_path, _, name = path.rpartition(".")
    module = __import__(module_path, fromlist=[name])
    return getattr(module, name)


def install(app: FastAPI) -> None:
    for path, status, code, message, fix, fix_path in _MAPPINGS:
        try:
            exc_cls = _import(path)
        except (ImportError, AttributeError):
            continue

        def _handler(request: Request, exc: Exception, status=status, code=code, message=message, fix=fix, fix_path=fix_path):
            detail = str(exc).strip()
            return JSONResponse(status_code=status, content=_body(code, f"{message} ({detail})" if detail and code != "UPLOAD_REJECTED" else (detail or message), fix, fix_path))

        app.add_exception_handler(exc_cls, _handler)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):  # noqa: ANN001
        from app.platform.ops.observability import request_id_var

        rid = request_id_var.get()
        log.exception("unhandled error (request %s)", rid)
        reason = (str(exc).strip().splitlines() or [""])[0][:200] or type(exc).__name__
        response = JSONResponse(status_code=500, content={"detail": {"code": "UNEXPECTED", "message": f"Something went wrong - {reason}",
                                                                     "fix": f"Please try again. If it keeps happening, contact support and quote reference {rid}.", "fix_path": "", "request_id": rid}})
        # Starlette runs this handler in ServerErrorMiddleware, OUTSIDE CORSMiddleware, so
        # without these headers the browser drops the body and the UI says "couldn't reach the server".
        origin = request.headers.get("origin")
        if origin and origin in cors_origins():
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response


def cors_origins() -> list[str]:
    import os

    # same list main.py gives CORSMiddleware
    return [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
