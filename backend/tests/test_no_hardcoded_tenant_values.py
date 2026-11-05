"""Hardcode guard (docs/HRMS_COMPLETE_SPEC.txt, Part 1, Step 3): a client-specific literal
must never live in backend/app or frontend/src -- see docs/hardcode_inventory.md for the
read-only audit this project's own baseline offenders came from, and section A of the spec
for the full "zero client-specific static values" rule this enforces.

A hard pass as of Part 4: every real offender from the Part 1 baseline was migrated into
the Settings Registry / Connections / Communication Engine (brand_theme, org.display_name,
message_templates) across Parts 2-4; what's left in `hardcode_allowlist.txt` is either a
UI placeholder, a generic non-client-specific scaffold default, or Part 1's own deliberate
frontend/src/bootstrap/defaults.ts staging point for Part 6's real branding API -- see that
file's own allowlist entries for the specific reasoning on each.

Patterns checked (exactly the list in Part 1, Step 3):
  - email addresses, outside tests/fixtures
  - "gmail.com"
  - "ctdtechs" / "CTD Techs" (any spacing/case)
  - absolute Windows/Unix user paths
  - ".xlsx" literals
  - hex colours -- scoped to backend/app only (frontend/src/theme's palette is a generic,
    already-neutral design-system token set, not client data; the spec's own Step 1 grep
    for this pattern was backend/app-only too). Every genuinely tenant-specific hex color
    (brand_theme's primary/gradient colors) is DATA now, sourced from platform/comms/ and
    threaded through negotiation_router.py's own {{PRIMARY}}/{{GRADIENT_FROM}}/
    {{GRADIENT_TO}} placeholders (Part 4 section 5) -- what's left as a literal is each
    page/email's own generic, non-brand status/neutral palette (see
    hardcode_allowlist.txt's own reasoning for each).
  - model IDs ("claude-..."), outside platform/ai/model_catalog.py (doesn't exist yet --
    an inert exclusion until Part 3 creates it)

`hardcode_allowlist.txt` (repo root) holds genuine exceptions: one `path:line_regex #
reason` per line, blank lines and lines starting with `#` ignored. `path` matches a
finding's path relative to the repo root; `line_regex` is matched against that finding's
exact source line.
"""

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_APP = REPO_ROOT / "backend" / "app"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
ALLOWLIST_FILE = REPO_ROOT / "hardcode_allowlist.txt"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", re.IGNORECASE)
_GMAIL_RE = re.compile(r"gmail\.com", re.IGNORECASE)
_CTD_RE = re.compile(r"ctdtechs|ctd\s*techs", re.IGNORECASE)
_ABS_PATH_RE = re.compile(r"\b[A-Za-z]:\\|/Users/[A-Za-z0-9_-]+|/home/[A-Za-z0-9_-]+")
_XLSX_RE = re.compile(r"\.xlsx")
_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}\b")
_MODEL_ID_RE = re.compile(r"claude-(3|haiku|sonnet|opus)")

# A finding's path is relative-to-repo-root and forward-slashed, so these substrings match
# regardless of which of the two scan roots (backend/app, frontend/src) it came from.
_TEST_OR_FIXTURE_MARKERS = ("/tests/", ".test.ts", ".test.tsx", "__pycache__/")

_MODEL_CATALOG_PATH = "backend/app/platform/ai/model_catalog.py"


@dataclass(frozen=True)
class Finding:
    path: str  # relative to REPO_ROOT, forward-slashed
    line_no: int
    line: str
    category: str


def _iter_source_files():
    for root in (BACKEND_APP, FRONTEND_SRC):
        if not root.exists():
            continue
        patterns = ["*.py"] if root is BACKEND_APP else ["*.ts", "*.tsx"]
        for pattern in patterns:
            for file_path in root.rglob(pattern):
                rel = file_path.relative_to(REPO_ROOT).as_posix()
                if any(marker in rel for marker in _TEST_OR_FIXTURE_MARKERS):
                    continue
                yield file_path, rel


def _scan_file(file_path: Path, rel: str) -> list[Finding]:
    findings: list[Finding] = []
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    is_backend = rel.startswith("backend/app/")
    for line_no, line in enumerate(text.splitlines(), start=1):
        if _EMAIL_RE.search(line):
            findings.append(Finding(rel, line_no, line, "email_address"))
        if _GMAIL_RE.search(line):
            findings.append(Finding(rel, line_no, line, "gmail.com"))
        if _CTD_RE.search(line):
            findings.append(Finding(rel, line_no, line, "ctdtechs"))
        if _ABS_PATH_RE.search(line):
            findings.append(Finding(rel, line_no, line, "absolute_path"))
        if _XLSX_RE.search(line):
            findings.append(Finding(rel, line_no, line, "xlsx_literal"))
        if is_backend and _HEX_COLOR_RE.search(line):
            findings.append(Finding(rel, line_no, line, "hex_color"))
        if _MODEL_ID_RE.search(line) and rel != _MODEL_CATALOG_PATH:
            findings.append(Finding(rel, line_no, line, "model_id"))
    return findings


def _load_allowlist() -> list[tuple[str, re.Pattern]]:
    if not ALLOWLIST_FILE.exists():
        return []
    entries: list[tuple[str, re.Pattern]] = []
    for raw_line in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        path, _, line_regex = line.partition(":")
        if not path or not line_regex:
            continue
        entries.append((path.strip(), re.compile(line_regex.strip())))
    return entries


def _is_allowlisted(finding: Finding, allowlist: list[tuple[str, re.Pattern]]) -> bool:
    return any(path == finding.path and pattern.search(finding.line) for path, pattern in allowlist)


def _collect_findings() -> list[Finding]:
    allowlist = _load_allowlist()
    findings: list[Finding] = []
    for file_path, rel in _iter_source_files():
        for finding in _scan_file(file_path, rel):
            if not _is_allowlisted(finding, allowlist):
                findings.append(finding)
    return findings


def test_no_hardcoded_tenant_values():
    findings = _collect_findings()
    if findings:
        lines = [f"{f.path}:{f.line_no} [{f.category}]  {f.line.strip()}" for f in findings]
        message = f"{len(findings)} hardcoded tenant-value offender(s) found:\n" + "\n".join(lines)
        assert not findings, message
