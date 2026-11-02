// Part 23.1: proof screenshots for Phase 0 (AI Intelligence settings + usage page, EN / HI / TA)
// into docs/ui/screens/p23-1-*.png. Runs against the proof stack (web :5174 -> API :8010).
// Needs Playwright installed WITHOUT saving it (see take_screenshots.mjs) and a token for a
// temporary admin in SHOT_TOKEN (never stored). Switches the provider to Bedrock and back.
import { chromium } from "playwright";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "ui", "screens");
const BASE = process.env.SHOT_BASE || "http://127.0.0.1:5174";
const API = process.env.SHOT_API || "http://127.0.0.1:8010";
const TOKEN = process.env.SHOT_TOKEN;
if (!TOKEN) throw new Error("SHOT_TOKEN is required");

// SHOT_CHROME: an already-installed Chromium when the Playwright version's own build is not downloaded
const browser = await chromium.launch(process.env.SHOT_CHROME ? { executablePath: process.env.SHOT_CHROME } : {});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light", reducedMotion: "reduce" });
await ctx.addInitScript(([tok, loc]) => {
  localStorage.setItem("hr_automation_token", tok);
  if (!localStorage.getItem("hrms.locale")) localStorage.setItem("hrms.locale", loc);
  // tours already seen: the module tour and the page tour would cover the screens
  localStorage.setItem("hrms.tours.seen", JSON.stringify(["setup", "inbox", "reports", "settings"]));
  localStorage.setItem("hrms.pagetours.seen", JSON.stringify(["settings", "genai", "genai-usage", "reports", "analytics"]));
}, [TOKEN, "en"]);
const page = await ctx.newPage();
const log = [];

async function go(path) {
  await page.goto(BASE + path, { waitUntil: "networkidle", timeout: 45000 });
  // first visit: a page tour ("Don't show again") and the settings intro dialog ("Done") can pop up late
  // (the intro dialog is modal and blocks clicks on the tour, so close it first)
  for (let i = 0, quiet = 0; i < 15 && quiet < 3; i++) {
    await page.waitForTimeout(700);
    const skip = page.getByRole("button", { name: /Don't show again|फिर न दिखाएँ|மீண்டும் காட்ட/ });
    const done = page.getByRole("dialog").getByRole("button", { name: /^(Done|हो गया|முடிந்தது)$/ });
    if (await done.count()) { await done.first().click(); quiet = 0; }
    else if (await skip.count()) { await skip.first().click(); quiet = 0; }
    else quiet++;
  }
  await page.waitForTimeout(400);
}
async function shot(name, opts = {}) {
  await page.screenshot({ path: join(OUT, `p23-1-${name}.png`), ...opts });
  log.push(`${name}: ok`);
}
async function provider() {
  const r = await page.request.get(`${API}/api/v1/ui/genai/settings`, { headers: { Authorization: `Bearer ${TOKEN}` } });
  return (await r.json()).provider;
}
async function chooseProvider(label) {
  await page.getByRole("combobox", { name: "Provider" }).click();
  await page.getByRole("option", { name: label }).click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1200);
}

try {
  // ---- EN: settings, provider list, Bedrock block, switch back ----
  await go("/settings/integrations/ai");
  await shot("ai-settings-anthropic");
  await page.getByRole("combobox", { name: "Provider" }).click();
  await page.waitForTimeout(400);
  await shot("ai-provider-options");
  await page.keyboard.press("Escape");
  await chooseProvider("Claude on Amazon Bedrock (AWS)");
  log.push(`provider after choosing Bedrock: ${await provider()}`);
  await page.getByText("Amazon Bedrock", { exact: true }).first().scrollIntoViewIfNeeded();
  await shot("ai-settings-bedrock");
  await chooseProvider("Anthropic Claude (direct)");
  log.push(`provider after switching back: ${await provider()}`);
  await shot("ai-settings-back-to-anthropic");

  // ---- EN: usage page with the unit-costs card + per-job table ----
  await go("/genai-usage");
  await shot("ai-usage-en", { fullPage: true });

  // ---- HI / TA labels ----
  // the signed-in language comes from the user's own preference (as the profile menu saves it)
  const setLang = (l) => page.request.put(`${API}/api/v1/me/preferences`, { headers: { Authorization: `Bearer ${TOKEN}` }, data: { locale: l } });
  for (const loc of ["hi", "ta"]) {
    await setLang(loc);
    await page.evaluate((l) => localStorage.setItem("hrms.locale", l), loc);
    await go("/genai-usage");
    await shot(`ai-usage-${loc}`, { fullPage: true });
    await go("/settings/integrations/ai");
    await shot(`ai-settings-${loc}`);
  }
  await setLang("en");
  await page.evaluate(() => localStorage.setItem("hrms.locale", "en"));
} catch (e) {
  log.push(`FAILED ${String(e).split("\n")[0]}`);
  await page.screenshot({ path: join(OUT, "p23-1-FAILED.png") }).catch(() => {});
} finally {
  log.push(`final provider: ${await provider().catch(() => "unknown")}`);
  console.log(log.join("\n"));
  await browser.close();
}
