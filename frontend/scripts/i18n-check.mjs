// Part 17.1: `npm run i18n:check` -- lists UI text keys used in the code (t("...")) that are
// missing from the English, Hindi or Tamil bundles (src/i18n/{en,hi,ta}.ts + src/i18n/pages/*.ts).
// Not a test suite: a static scan that exits 1 when anything is missing, so `npm run build` stops.
//   node scripts/i18n-check.mjs            report + exit code
//   node scripts/i18n-check.mjs --json     machine-readable list (used when filling gaps)
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const I18N = join(ROOT, "i18n");
const LOCALES = ["en", "hi", "ta"];

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(tsx?|mts)$/.test(name) && !/\.d\.ts$/.test(name)) out.push(p);
  }
  return out;
}

// Keys in a bundle file, per exported locale block (`export const en = {` ... `};`).
function bundleKeys(file) {
  const src = readFileSync(file, "utf8");
  const result = {};
  const re = /export const (en|hi|ta)\b[^=]*=\s*\{([\s\S]*?)\n\}(?: as const)?;/g;
  let m;
  while ((m = re.exec(src))) {
    const keys = result[m[1]] ?? (result[m[1]] = new Set());
    for (const k of m[2].matchAll(/^\s*"([^"]+)"\s*:/gm)) keys.add(k[1]);
  }
  return result;
}

const have = Object.fromEntries(LOCALES.map((l) => [l, new Set()]));
const bundleFiles = [...LOCALES.map((l) => join(I18N, `${l}.ts`)), ...readdirSync(join(I18N, "pages")).filter((f) => f.endsWith(".ts")).map((f) => join(I18N, "pages", f))];
for (const file of bundleFiles) {
  const found = bundleKeys(file);
  // the shared files export one locale each (en.ts -> en, ...)
  for (const [locale, keys] of Object.entries(found)) for (const k of keys) have[locale].add(k);
}

// Keys used in code: t("a.b") / t('a.b') / tr("a.b"), plus labelKey/label_key: "a.b" literals.
const used = new Map(); // key -> first file
const prefixes = new Map(); // `a.b.${x}` -> file
const CALL = /(?<![\w.])(?:t|tr)\(\s*(["'`])([a-zA-Z0-9_.-]+(?:\$\{[^}]*\}[a-zA-Z0-9_.-]*)*)\1/g;
const LABEL = /\b(?:labelKey|label_key|titleKey|hintKey)\s*[:=]\s*["']([a-zA-Z][\w.-]*\.[\w.-]+)["']/g;
for (const file of walk(ROOT)) {
  if (file.startsWith(I18N)) continue;
  const src = readFileSync(file, "utf8");
  const rel = relative(ROOT, file);
  for (const m of src.matchAll(CALL)) {
    const key = m[2];
    if (!key.includes(".")) continue;
    if (key.includes("${")) { if (!prefixes.has(key)) prefixes.set(key, rel); continue; }
    if (!used.has(key)) used.set(key, rel);
  }
  for (const m of src.matchAll(LABEL)) if (!used.has(m[1])) used.set(m[1], rel);
}

const missing = [];
for (const [key, file] of used) for (const l of LOCALES) if (!have[l].has(key) && !have[l].has(`${key}_one`)) missing.push({ key, locale: l, file });
// A dynamic key (t(`x.${y}`)) passes when at least one key with its fixed prefix exists in each locale.
for (const [pattern, file] of prefixes) {
  const prefix = pattern.split("${")[0];
  if (!prefix.includes(".")) continue;
  for (const l of LOCALES) if (![...have[l]].some((k) => k.startsWith(prefix))) missing.push({ key: pattern, locale: l, file });
}

if (process.argv.includes("--json")) {
  console.log(JSON.stringify(missing, null, 1));
} else {
  const byLocale = Object.fromEntries(LOCALES.map((l) => [l, missing.filter((x) => x.locale === l)]));
  for (const l of LOCALES) {
    console.log(`${l}: ${byLocale[l].length} missing`);
    for (const x of byLocale[l].slice(0, 40)) console.log(`  ${x.key}   (${x.file})`);
    if (byLocale[l].length > 40) console.log(`  … and ${byLocale[l].length - 40} more`);
  }
  console.log(missing.length ? `i18n:check FAILED -- ${missing.length} missing` : `i18n:check OK -- ${used.size} keys, 0 missing`);
}
process.exit(missing.length ? 1 : 0);
