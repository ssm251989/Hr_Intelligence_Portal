// Part 23.1b: Bedrock keeps its own "last test" + the settings menu reads "AI Intelligence & HR assistant".
// Proof stack (web :5174 -> API :8010), temp admin token in SHOT_TOKEN (never stored), SHOT_CHROME as in p23_ai_shots.mjs.
// Switches the provider to Bedrock, presses Test once (no AWS access here -> a failed test is expected), switches back.
import { chromium } from "playwright";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "ui", "screens");
const BASE = process.env.SHOT_BASE || "http://127.0.0.1:5174";
const API = process.env.SHOT_API || "http://127.0.0.1:8010";
const TOKEN = process.env.SHOT_TOKEN;
if (!TOKEN) throw new Error("SHOT_TOKEN is required");

const browser = await chromium.launch(process.env.SHOT_CHROME ? { executablePath: process.env.SHOT_CHROME } : {});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light", reducedMotion: "reduce" });
await ctx.addInitScript((tok) => {
  localStorage.setItem("hr_automation_token", tok);
  localStorage.setItem("hrms.locale", "en");
  localStorage.setItem("hrms.tours.seen", JSON.stringify(["setup", "inbox", "reports", "settings"]));
  localStorage.setItem("hrms.pagetours.seen", JSON.stringify(["settings", "genai", "genai-usage", "reports", "analytics"]));
}, TOKEN);
const page = await ctx.newPage();
const log = [];
const auth = { headers: { Authorization: `Bearer ${TOKEN}` } };

async function go(path) {
  await page.goto(BASE + path, { waitUntil: "networkidle", timeout: 45000 });
  for (let i = 0, quiet = 0; i < 15 && quiet < 3; i++) {
    await page.waitForTimeout(700);
    const skip = page.getByRole("button", { name: /Don't show again/ });
    const done = page.getByRole("dialog").getByRole("button", { name: /^Done$/ });
    if (await done.count()) { await done.first().click(); quiet = 0; }
    else if (await skip.count()) { await skip.first().click(); quiet = 0; }
    else quiet++;
  }
  await page.waitForTimeout(400);
}
const shot = async (name, opts = {}) => { await page.screenshot({ path: join(OUT, `p23-1b-${name}.png`), ...opts }); log.push(`${name}: ok`); };
const settings = async () => (await page.request.get(`${API}/api/v1/ui/genai/settings`, auth)).json();
async function chooseProvider(label) {
  await page.getByRole("combobox", { name: "Provider" }).click();
  await page.getByRole("option", { name: label }).click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1200);
}
const statusLine = async () => (await page.getByText(/In use today/).first().innerText().catch(() => "?")).replace(/\s+/g, " ");

try {
  await go("/settings");
  await shot("settings-home");
  await page.getByText("Integrations", { exact: true }).first().click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1200);
  log.push(`integrations url: ${page.url()}`);
  const entry = page.getByText("AI Intelligence & HR assistant").first();
  log.push(`menu entry visible: ${await entry.isVisible().catch(() => false)}`);
  await entry.scrollIntoViewIfNeeded().catch(() => {});
  await shot("settings-menu");

  await go("/settings/integrations/ai");
  log.push(`anthropic line: ${await statusLine()}`);
  await shot("anthropic-own-test");
  await chooseProvider("Claude on Amazon Bedrock (AWS)");
  log.push(`provider: ${(await settings()).provider}`);
  log.push(`bedrock line (before Test): ${await statusLine()}`);
  await shot("bedrock-not-tested");
  // wait for the test itself (a Bedrock test without AWS access takes ~8 s: credential lookup)
  const tested = page.waitForResponse((r) => r.url().endsWith("/api/v1/ui/genai/test"), { timeout: 60000 });
  await page.getByRole("button", { name: /^Test$/ }).first().click();
  log.push(`test response: ${JSON.stringify(await (await tested).json())}`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1500);
  const s = await settings();
  log.push(`after Test: bedrock last_tested_at=${s.bedrock.last_tested_at} ok=${s.bedrock.last_test_ok}; anthropic key last=${s.key.last_tested_at} ok=${s.key.last_test_ok}`);
  log.push(`bedrock line (after Test): ${await statusLine()}`);
  await shot("bedrock-after-test");
  await chooseProvider("Anthropic Claude (direct)");
  log.push(`provider back: ${(await settings()).provider}; line: ${await statusLine()}`);
  await shot("back-to-anthropic");
} catch (e) {
  log.push(`FAILED ${String(e).split("\n")[0]}`);
  await page.screenshot({ path: join(OUT, "p23-1b-FAILED.png") }).catch(() => {});
} finally {
  log.push(`final provider: ${(await settings().catch(() => ({}))).provider}`);
  console.log(log.join("\n"));
  await browser.close();
}
