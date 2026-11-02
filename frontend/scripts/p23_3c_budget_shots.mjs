// Part 23.3c: on-screen proof of 21.7 (budget released on exit: pro-rata and full, release history on the Finance dashboard).
// env: SHOT_TOKEN, SHOT_CHROME, P23_SEP1, P23_SEP2 (two exits in clearance with a past last working day)
import { chromium } from "playwright";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "ui", "screens");
const BASE = "http://127.0.0.1:5174", API = "http://127.0.0.1:8010";
const { SHOT_TOKEN: TOKEN, P23_SEP1: SEP1, P23_SEP2: SEP2 } = process.env;
if (!TOKEN || !SEP1 || !SEP2) throw new Error("SHOT_TOKEN, P23_SEP1, P23_SEP2 are required");

const browser = await chromium.launch(process.env.SHOT_CHROME ? { executablePath: process.env.SHOT_CHROME } : {});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light", reducedMotion: "reduce" });
await ctx.addInitScript((tok) => {
  localStorage.setItem("hr_automation_token", tok);
  localStorage.setItem("hrms.locale", "en");
  localStorage.setItem("hrms.tours.seen", JSON.stringify(["setup", "inbox", "reports", "settings", "hiring"]));
  localStorage.setItem("hrms.pagetours.seen", JSON.stringify(["settings", "salary", "finance", "employees", "budgets"]));
}, TOKEN);
const page = await ctx.newPage();
const log = [];
const auth = { headers: { Authorization: `Bearer ${TOKEN}` } };

async function settle() {
  for (let i = 0, quiet = 0; i < 12 && quiet < 3; i++) {
    await page.waitForTimeout(600);
    const skip = page.getByRole("button", { name: /Don't show again/ });
    const done = page.getByRole("dialog").getByRole("button", { name: /^Done$/ });
    if (await done.count()) { await done.first().click(); quiet = 0; }
    else if (await skip.count()) { await skip.first().click(); quiet = 0; }
    else quiet++;
  }
}
async function go(path) { await page.goto(BASE + path, { waitUntil: "networkidle", timeout: 45000 }); await settle(); }
const shot = async (name, opts = {}) => { await page.screenshot({ path: join(OUT, `p23-3c-${name}.png`), ...opts }); log.push(`shot ${name}`); };
async function step(name, fn) {
  try { await fn(); } catch (e) { log.push(`FAILED ${name}: ${String(e).split("\n")[0]}`); await page.screenshot({ path: join(OUT, `p23-3c-FAILED-${name}.png`) }).catch(() => {}); }
}
async function complete(sep, label) {
  const r = await page.request.post(`${API}/api/v1/ui/exit-checklist/separations/${sep}/complete`, { ...auth, data: {} });
  const body = await r.json();
  log.push(`complete ${label}: HTTP ${r.status()} status=${body.status ?? body.separation?.status ?? JSON.stringify(body).slice(0, 160)}`);
}
async function finance(name) {
  await go("/salary?tab=finance");
  const card = page.getByText("Budget history - money released").first();
  await card.scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  await shot(name);
  const items = await card.locator("xpath=..").innerText().catch(() => "");
  log.push(`${name} history: ${items.replace(/\s+/g, " ").slice(0, 400)}`);
}
async function mode(label) {
  await go("/settings/hiring/budgets");
  await page.getByText("Release budget on exit").first().scrollIntoViewIfNeeded();
  if (label) {
    await page.getByLabel(label).check();
    await page.waitForLoadState("networkidle"); await page.waitForTimeout(1200);
  }
}

try {
  await step("before", async () => {
    await go("/salary?tab=finance");
    await shot("finance-before", { fullPage: true });
    await mode(null);
    await shot("settings-pro-rata-default");
  });
  await step("pro-rata", async () => {
    await complete(SEP1, "Proof Karan Mehta (pro-rata)");
    await finance("finance-after-pro-rata");
  });
  await step("full", async () => {
    await mode("Release the full annual amount");
    await shot("settings-full");
    await complete(SEP2, "Proof Divya Nair (full)");
    await finance("finance-after-full");
    await go("/salary?tab=finance");
    await shot("finance-after-full-page", { fullPage: true });
  });
  await step("back", async () => {
    await mode("Release for the remaining months of the budget year (pro-rata)");
    await shot("settings-back-to-pro-rata");
  });
} finally {
  console.log(log.join("\n"));
  await browser.close();
}
