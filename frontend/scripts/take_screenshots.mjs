// Part 15.9: one light-mode screenshot per page into docs/ui/screens/ (screenshots only, no tests).
//
// Needs Playwright, installed WITHOUT adding it to package.json (run inside frontend/):
//   npm i --no-save playwright; npx playwright install chromium
// Signs in with an account YOU provide through environment variables (never stored):
//   PowerShell:  $env:SHOT_EMAIL="you@company.com"; $env:SHOT_PASSWORD="..."; node scripts/take_screenshots.mjs
// Optional: SHOT_BASE (default http://localhost:5173), SHOT_AGENCY_EMAIL / SHOT_AGENCY_PASSWORD
// for the agency portal, SHOT_ONLY=home,jobs to retake a few.
// Use a Super Admin / HR Admin login so every staff page is visible. Pages with an :id use
// the first row of the matching list page.
import { chromium } from "playwright";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "ui", "screens");
const BASE = process.env.SHOT_BASE || "http://localhost:5173";
const ONLY = (process.env.SHOT_ONLY || "").split(",").filter(Boolean);

const PUBLIC = [["login", "/login"], ["register", "/register"], ["set-password", "/set-password"], ["careers", "/careers"]];
const STAFF = [
  ["home", "/"], ["overview", "/overview"], ["approvals", "/approvals"], ["jobs", "/jobs"],
  ["candidates", "/candidates/list"], ["screening", "/screening/dashboard"], ["shortlisting", "/shortlisting/dashboard"],
  ["interviews", "/interviews/dashboard"], ["hr-inbox", "/hr-inbox"], ["salary", "/salary"], ["bgv", "/bgv"], ["offers", "/offers"],
  ["agencies", "/agencies"], ["reports", "/reports"], ["analytics", "/analytics"], ["onboarding", "/onboarding"],
  ["employees", "/employees"], ["directory", "/directory"], ["org-chart", "/org-chart"], ["performance", "/performance"],
  ["compensation", "/compensation"], ["succession", "/succession"], ["helpdesk", "/helpdesk"], ["assets", "/assets"],
  ["exits", "/exits"], ["setup", "/setup"], ["settings", "/settings"],
];
// name -> [list page, link prefix to follow]
const DETAIL = { "candidate-profile": ["/candidates/list", "/candidates/"], "employee-profile": ["/employees", "/employees/"] };

const want = (name) => !ONLY.length || ONLY.includes(name);
const results = [];

async function shot(page, name, path) {
  if (!want(name)) return;
  try {
    await page.goto(BASE + path, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: join(OUT, `${name}.png`), fullPage: true });
    results.push(`${name}: ok`);
  } catch (e) {
    results.push(`${name}: FAILED ${String(e).split("\n")[0]}`);
  }
}

async function signIn(page, email, password) {
  await page.goto(BASE + "/login", { waitUntil: "networkidle" });
  await page.locator('input[type="email"], input[name="email"]').first().fill(email);
  await page.locator('input[type="password"]').first().fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 20000 });
}

const browser = await chromium.launch();
const newPage = async () => (await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light", reducedMotion: "reduce" })).newPage();

const pub = await newPage();
for (const [n, p] of PUBLIC) await shot(pub, n, p);
if (want("careers-job")) {
  await pub.goto(BASE + "/careers", { waitUntil: "networkidle" });
  const view = pub.getByText("View job").first();
  if (await view.count()) { await view.click(); await pub.waitForLoadState("networkidle"); await shot(pub, "careers-job", new URL(pub.url()).pathname); }
  else results.push("careers-job: skipped (no published job)");
}

if (process.env.SHOT_EMAIL && process.env.SHOT_PASSWORD) {
  const staff = await newPage();
  await signIn(staff, process.env.SHOT_EMAIL, process.env.SHOT_PASSWORD);
  for (const [n, p] of STAFF) await shot(staff, n, p);
  for (const [n, [list, prefix]] of Object.entries(DETAIL)) {
    if (!want(n)) continue;
    await staff.goto(BASE + list, { waitUntil: "networkidle" });
    const href = await staff.locator(`a[href^="${prefix}"]`).first().getAttribute("href").catch(() => null);
    if (href) await shot(staff, n, href); else results.push(`${n}: skipped (no rows)`);
  }
  await shot(staff, "superadmin", "/superadmin");
} else {
  results.push("staff pages: skipped (set SHOT_EMAIL and SHOT_PASSWORD)");
}

if (process.env.SHOT_AGENCY_EMAIL && process.env.SHOT_AGENCY_PASSWORD) {
  const agency = await newPage();
  await signIn(agency, process.env.SHOT_AGENCY_EMAIL, process.env.SHOT_AGENCY_PASSWORD);
  await shot(agency, "agency", "/agency");
}

await browser.close();
console.log(results.join("\n"));
