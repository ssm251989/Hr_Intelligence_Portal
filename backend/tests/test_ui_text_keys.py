"""ST2 (Part 27): UI text for keys the backend hands the frontend at run time - every connection purpose
(Settings > Integrations), every module code and menu label - must exist in English, Hindi and Tamil.
`npm run i18n:check` can't see these (they are not literals in the frontend code)."""

import re
from pathlib import Path

I18N = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n"


def _keys() -> dict[str, set[str]]:
    have = {"en": set(), "hi": set(), "ta": set()}
    files = [I18N / f"{loc}.ts" for loc in have] + sorted((I18N / "pages").glob("*.ts"))
    for f in files:
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"export const (en|hi|ta)\b[^=]*=\s*\{([\s\S]*?)\n\}(?: as const)?;", src):
            have[m.group(1)].update(re.findall(r'^\s*"([^"]+)"\s*:', m.group(2), re.M))
    return have


def test_every_connection_purpose_has_a_name():
    from app.platform.connectors.purposes import all_purposes

    have = _keys()
    for loc, keys in have.items():
        assert [p for p in all_purposes() if f"purpose.{p}" not in keys] == [], loc


def test_every_module_and_menu_label_has_a_name():
    from app.platform.modules import MODULES

    wanted = {f"nav.{m.code}" for m in MODULES}
    wanted |= {n.label_key for m in MODULES for n in m.nav}
    have = _keys()
    for loc, keys in have.items():
        assert sorted(k for k in wanted if k not in keys) == [], loc
