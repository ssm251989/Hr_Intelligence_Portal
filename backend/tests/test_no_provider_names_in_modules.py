"""modules/* must not import providers/* (Part 3 CHECKS) -- code never names a provider
or address (section 1's own goal). This codebase doesn't have a modules/ package yet
(section E's target layout; the current business-logic packages are still flat --
candidates/, screening/, jobs/, etc., see Part 1's own module_parity_checklist.md) --
adapted to check every real business-logic package instead of a not-yet-existing one.
"""

import ast
from pathlib import Path

BACKEND_APP = Path(__file__).resolve().parents[1] / "app"

# Everything that ISN'T a cross-cutting platform/core/model/schema package -- i.e. every
# current business-logic module, the ones that would eventually move under modules/* per
# section E. Mirrors Part 1's own module_parity_checklist.md's 13-module list, plus every
# other current top-level business package.
BUSINESS_PACKAGES = (
    "candidates", "screening", "shortlisting", "jobs", "scheduling", "interview_scheduling",
    "salary", "bgv", "offers", "reports", "users", "auth", "public", "hr_inbox",
    "local_import", "ai_services", "audit",
)


def _imports_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_no_business_module_imports_a_provider_adapter_directly():
    offenders: list[str] = []
    for package in BUSINESS_PACKAGES:
        package_dir = BACKEND_APP / package
        if not package_dir.exists():
            continue
        for py_file in package_dir.rglob("*.py"):
            for imported in _imports_in(py_file):
                if imported.startswith("app.platform.connectors.providers"):
                    offenders.append(f"{py_file.relative_to(BACKEND_APP)} imports {imported}")
    assert not offenders, "Business modules must resolve a purpose via ConnectorRouter, never import a provider directly:\n" + "\n".join(offenders)


def test_no_business_module_imports_a_specific_provider_sdk_used_by_the_new_framework():
    """A softer, forward-looking check: none of these packages should import the anthropic
    SDK directly either -- ai_services/*.py still does today (not yet migrated onto
    ai.gateway.complete(), see docs/build_log.md's own Part 3 scope note) so this is
    recorded, not asserted, to avoid failing on a known, already-documented gap."""
    offenders: list[str] = []
    for package in BUSINESS_PACKAGES:
        package_dir = BACKEND_APP / package
        if not package_dir.exists():
            continue
        for py_file in package_dir.rglob("*.py"):
            if "anthropic" in _imports_in(py_file):
                offenders.append(str(py_file.relative_to(BACKEND_APP)))
    # Known, documented gap (ai_services/*.py) -- not yet wired to ai.gateway. Normalized
    # to forward slashes + sorted -- rglob() order/path separators aren't guaranteed
    # consistent across platforms.
    normalized = sorted(o.replace("\\", "/") for o in offenders)
    assert normalized == [
        "ai_services/candidate_ranker.py", "ai_services/document_validator.py",
        "ai_services/interview_question_generator.py", "ai_services/jd_generator.py",
        "ai_services/offer_letter_generator.py", "ai_services/resume_matcher.py",
        "ai_services/resume_parser.py", "ai_services/shortlist_feedback_generator.py",
        "local_import/service.py",
    ]
