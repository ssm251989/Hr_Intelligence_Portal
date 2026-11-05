// Part 23.3e (22.4): Employees > Assign roles - single (row menu, create account + invite, HR Admin) and bulk
// (2 employees, add Finance; one without an account), the "access updated" / invite emails in mailpit.
// env: SHOT_TOKEN, SHOT_CHROME. Data: p23fx.py roles-setup (Proof Roleone Kapoor, Proof Roletwo Iyer, no accounts).
import { chromium } from "playwright";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "ui", "screens");
const BASE = "http://127.0.0.1:5174", MP = "http://127.0.0.1:8025";
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
const shot = async (name, opts = {}) => { await page.screenshot({ path: join(OUT, `p23-3e-${name}.png`), ...opts }); log.push(`shot ${name}`); };
async function step(name, fn) {
  try { await fn(); } catch (e) { log.push(`FAILED ${name}: ${String(e).split("\n")[0]}`); await page.screenshot({ path: join(OUT, `p23-3e-FAILED-${name}.png`) }).catch(() => {}); await page.keyboard.press("Escape").catch(() => {}); }
}
async function employees() {
  await page.goto(BASE + "/employees", { waitUntil: "load", timeout: 60000 }); await page.waitForTimeout(2500); await settle();
  await page.getByLabel("Search name, ID, email, phone").fill("Proof Role");
  await page.waitForTimeout(1500);
}
async function mailShots() {
  const msgs = (await (await page.request.get(`${MP}/api/v1/messages?limit=30`)).json()).messages ?? [];
  const mine = msgs.filter((m) => m.To.some((t) => /proof\.role/.test(t.Address)));
  for (const m of mine) log.push(`mailpit: "${m.Subject}" -> ${m.To.map((t) => t.Address).join(", ")}`);
  let i = 0;
  for (const m of mine.slice(0, 3)) {
    const p2 = await ctx.newPage();
    await p2.goto(`${MP}/view/${m.ID}`, { waitUntil: "networkidle" }); await p2.waitForTimeout(800);
    await p2.screenshot({ path: join(OUT, `p23-3e-roles-mail-${++i}.png`) });
    await p2.close();
  }
}

try {
  await step("single", async () => {
    await employees();
    await shot("roles-employees");
    await page.getByRole("button", { name: /Actions for Proof Roleone/ }).click();
    await page.getByRole("menuitem", { name: "Assign roles" }).click();
    const dlg = page.getByRole("dialog");
    await dlg.waitFor();
    await dlg.getByLabel("Create account and send invite").check();
    await dlg.getByRole("checkbox", { name: "HR Admin", exact: true }).check();
    await page.waitForTimeout(400);
    await shot("roles-single-dialog");
    await dlg.getByRole("button", { name: "Save", exact: true }).click();
    await page.waitForTimeout(2500);
    log.push(`single result: ${(await dlg.innerText().catch(() => "(closed)")).replace(/\s+/g, " ").slice(0, 300)}`);
    await shot("roles-single-result");
    await page.keyboard.press("Escape");
  });
  await step("bulk", async () => {
    await employees();
    for (const n of ["Proof Roleone Kapoor", "Proof Roletwo Iyer"]) await page.getByRole("checkbox", { name: n }).check();
    await page.getByRole("button", { name: "Assign roles (2)" }).click();
    const dlg = page.getByRole("dialog");
    await dlg.waitFor();
    await page.waitForTimeout(800);
    await shot("roles-bulk-dialog-before");
    await dlg.getByRole("checkbox", { name: "Finance", exact: true }).check();
    await page.waitForTimeout(400);
    await shot("roles-bulk-dialog");
    await dlg.getByRole("button", { name: "Save", exact: true }).click();
    await page.waitForTimeout(2500);
    log.push(`bulk result: ${(await dlg.innerText().catch(() => "(closed)")).replace(/\s+/g, " ").slice(0, 400)}`);
    await shot("roles-bulk-result");
    await page.keyboard.press("Escape");
    await employees();
    await shot("roles-employees-after");
  });
  await step("mails", mailShots);
} finally {
  console.log(log.join("\n"));
  await browser.close();
}
