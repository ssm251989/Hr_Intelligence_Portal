// Part 23.3e (22.5): Agencies - Delete agency: no history -> delete; history -> deactivate (Inactive filter, Restore);
// open BGV cases -> blocked. env: SHOT_TOKEN, SHOT_CHROME. Data: p23fx.py agencydel-setup.
import { chromium } from "playwright";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "ui", "screens");
const BASE = "http://127.0.0.1:5174", API = "http://127.0.0.1:8010";
const TOKEN = process.env.SHOT_TOKEN;
if (!TOKEN) throw new Error("SHOT_TOKEN is required");

const browser = await chromium.launch(process.env.SHOT_CHROME ? { executablePath: process.env.SHOT_CHROME } : {});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light", reducedMotion: "reduce" });
await ctx.addInitScript((tok) => {
  localStorage.setItem("hr_automation_token", tok);
  localStorage.setItem("hrms.locale", "en");
  localStorage.setItem("hrms.tours.seen", JSON.stringify(["setup", "inbox", "reports", "settings", "hiring", "people"]));
  localStorage.setItem("hrms.pagetours.seen", JSON.stringify(["home", "employees", "approvals", "agencies"]));
}, TOKEN);
const page = await ctx.newPage();
const log = [];
const auth = { headers: { Authorization: `Bearer ${TOKEN}` } };

async function settle() {
  for (let i = 0, quiet = 0; i < 12 && quiet < 3; i++) {
    await page.waitForTimeout(600);
    const skip = page.getByRole("button", { name: /Don't show again/ });
    if (await skip.count()) { await skip.first().click(); quiet = 0; } else quiet++;
  }
}
const shot = async (name, opts = {}) => { await page.screenshot({ path: join(OUT, `p23-3e-${name}.png`), ...opts }); log.push(`shot ${name}`); };
async function step(name, fn) {
  try { await fn(); } catch (e) { log.push(`FAILED ${name}: ${String(e).split("\n")[0]}`); await page.screenshot({ path: join(OUT, `p23-3e-FAILED-${name}.png`) }).catch(() => {}); await page.keyboard.press("Escape").catch(() => {}); }
}
async function agencies() { await page.goto(BASE + "/agencies", { waitUntil: "load", timeout: 60000 }); await page.waitForTimeout(2500); await settle(); }
const list = async (status) => (await (await page.request.get(`${API}/api/v1/agencies${status ? `?status=${status}` : ""}`, auth)).json());
async function openDelete(name) {
  await page.getByRole("button", { name: `More for ${name}` }).click();
  await page.getByRole("menuitem", { name: "Delete agency" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.waitFor(); await page.waitForTimeout(1000);
  return dlg;
}

try {
  await step("open-bgv-blocked", async () => {
    await agencies();
    await shot("agdel-list");
    const dlg = await openDelete("Proof OpenBGV Agency (P23)");
    log.push(`open BGV dialog: ${(await dlg.innerText()).replace(/\s+/g, " ").slice(0, 300)}`);
    await shot("agdel-open-bgv-blocked");
    await page.keyboard.press("Escape");
  });
  await step("delete-empty", async () => {
    await agencies();
    const dlg = await openDelete("Proof Empty Agency (P23)");
    log.push(`empty dialog: ${(await dlg.innerText()).replace(/\s+/g, " ").slice(0, 300)}`);
    await shot("agdel-empty-dialog");
    await dlg.getByRole("button", { name: "Delete", exact: true }).click();
    await page.waitForTimeout(2000);
    await shot("agdel-empty-deleted");
    log.push(`empty agency still in DB list (all): ${(await list("all")).some((a) => a.name === "Proof Empty Agency (P23)")}`);
  });
  await step("deactivate-history", async () => {
    await agencies();
    const dlg = await openDelete("Proof History Agency (P23)");
    log.push(`history dialog: ${(await dlg.innerText()).replace(/\s+/g, " ").slice(0, 300)}`);
    await shot("agdel-history-dialog");
    await dlg.getByRole("button", { name: "Deactivate", exact: true }).click();
    await page.waitForTimeout(2000);
    await shot("agdel-history-deactivated");
    const row = (await list("all")).find((a) => a.name === "Proof History Agency (P23)");
    log.push(`history agency after: active=${row?.active}`);
  });
  await step("inactive-restore", async () => {
    await agencies();
    await page.getByRole("combobox", { name: "Status" }).click();
    await page.getByRole("option", { name: "Inactive", exact: true }).click();
    await page.waitForTimeout(1500);
    await page.getByText("Proof History Agency (P23)", { exact: true }).first().click();
    await page.waitForTimeout(1200);
    await shot("agdel-inactive-filter");
    await page.getByRole("button", { name: "Restore", exact: true }).first().click();
    await page.waitForTimeout(2000);
    await shot("agdel-restored");
    const row = (await list("all")).find((a) => a.name === "Proof History Agency (P23)");
    log.push(`history agency after restore: active=${row?.active}`);
  });
} finally {
  console.log(log.join("\n"));
  await browser.close();
}
