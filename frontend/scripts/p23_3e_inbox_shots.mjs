// Part 23.3e (22.2 + 22.3): candidate emails tabs, "Not linked yet" + suggestions, manual link with "remember this
// address", rule chips, Closed; then the highlighted candidate-email cards (unread bold / read) in My approvals.
// env: SHOT_TOKEN, SHOT_CHROME. Data: p23fx.py inbox-setup (7 proof emails).
import { chromium } from "playwright";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "ui", "screens");
const BASE = "http://127.0.0.1:5174";
const TOKEN = process.env.SHOT_TOKEN;
if (!TOKEN) throw new Error("SHOT_TOKEN is required");

const browser = await chromium.launch(process.env.SHOT_CHROME ? { executablePath: process.env.SHOT_CHROME } : {});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light", reducedMotion: "reduce" });
await ctx.addInitScript((tok) => {
  localStorage.setItem("hr_automation_token", tok);
  localStorage.setItem("hrms.locale", "en");
  localStorage.setItem("hrms.tours.seen", JSON.stringify(["setup", "inbox", "reports", "settings", "hiring"]));
  localStorage.setItem("hrms.pagetours.seen", JSON.stringify(["home", "settings", "inbox", "candidate-emails", "approvals"]));
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
async function go(path) { await page.goto(BASE + path, { waitUntil: "load", timeout: 60000 }); await page.waitForTimeout(2500); await settle(); }
const shot = async (name, opts = {}) => { await page.screenshot({ path: join(OUT, `p23-3e-${name}.png`), ...opts }); log.push(`shot ${name}`); };
async function step(name, fn) {
  try { await fn(); } catch (e) { log.push(`FAILED ${name}: ${String(e).split("\n")[0]}`); await page.screenshot({ path: join(OUT, `p23-3e-FAILED-${name}.png`) }).catch(() => {}); }
}
const cardOf = (subject) => page.locator("li").filter({ hasText: subject }).first();
async function tab(label) {
  await page.getByRole("tab", { name: new RegExp(`^${label}`) }).click();
  await page.waitForTimeout(1500);
}

try {
  await step("needs-action", async () => {
    await go("/candidate-emails");
    log.push(`tabs: ${(await page.getByRole("tab").allInnerTexts()).join(" | ")}`);
    await shot("emails-needs-action", { fullPage: true });
    await cardOf("I am free on Monday").scrollIntoViewIfNeeded();
    await cardOf("I am free on Monday").click();
    await page.waitForTimeout(1200);
    log.push(`ambiguous card: ${(await cardOf("I am free on Monday").innerText()).replace(/\s+/g, " ").slice(0, 200)}`);
    await shot("emails-not-linked-suggestions");
  });
  await step("manual-link-remember", async () => {
    await cardOf("can I reschedule my call").click();
    await page.waitForTimeout(1200);
    const search = page.getByLabel("Search candidate by name or email");
    await search.scrollIntoViewIfNeeded();
    await search.fill("Meena");
    await page.waitForTimeout(1500);
    await page.getByRole("option", { name: /Meena Sundar/ }).first().click();
    const remember = page.getByLabel(/Also remember vikas\.unknown\.p23@example\.org/);
    log.push(`remember box checked by default: ${await remember.isChecked()}`);
    await shot("emails-manual-link-remember");
    await page.getByRole("button", { name: "Link email" }).click();
    await page.waitForTimeout(2000);
    await shot("emails-manual-linked");
  });
  await step("suggestion-link", async () => {
    await go("/candidate-emails");
    const btn = cardOf("I am free on Monday").getByRole("button", { name: "Link to Arun Prakash" });
    await btn.click();
    await page.waitForTimeout(2000);
    await shot("emails-linked-from-suggestion");
  });
  await step("linked-tab", async () => {
    await go("/candidate-emails");
    await tab("Linked to a candidate");
    log.push(`linked tab: ${(await page.locator("li").allInnerTexts()).map((x) => x.replace(/\s+/g, " ").slice(0, 120)).join(" || ")}`);
    await shot("emails-linked-tab", { fullPage: true });
  });
  await step("closed-tab", async () => {
    await tab("Closed");
    await shot("emails-closed-tab", { fullPage: true });
  });
  await step("approvals", async () => {
    await go("/approvals");
    const badge = await page.getByRole("link", { name: /My approvals/ }).first().innerText().catch(() => "?");
    log.push(`sidebar: ${badge.replace(/\s+/g, " ")}`);
    await shot("approvals-candidate-emails", { fullPage: true });
  });
} finally {
  console.log(log.join("\n"));
  await browser.close();
}
