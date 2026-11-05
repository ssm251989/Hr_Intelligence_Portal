// Part 23.3f (22.6): letters (one PDF per kind from the live Settings preview) + designed emails ("Send test to me"
// -> mailpit -> Gmail-width and phone-width screenshots) into docs/ui/letters/*-live.*. env: SHOT_TOKEN, SHOT_CHROME.
import { chromium } from "playwright";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { writeFileSync } from "node:fs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "ui");
const LET = join(ROOT, "letters"), SCR = join(ROOT, "screens");
const BASE = "http://127.0.0.1:5174", API = "http://127.0.0.1:8010", MP = "http://127.0.0.1:8025";
const TOKEN = process.env.SHOT_TOKEN;
if (!TOKEN) throw new Error("SHOT_TOKEN is required");
const EMAILS = { "recruitment.offer_letter_auto": "offer", "recruitment.welcome_selected": "welcome", "employee.exit_letters": "exit-letters" };
const KINDS = ["offer", "joining", "appointment", "confirmation", "relieving", "experience"];

const browser = await chromium.launch(process.env.SHOT_CHROME ? { executablePath: process.env.SHOT_CHROME } : {});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light", reducedMotion: "reduce", acceptDownloads: true });
await ctx.addInitScript((tok) => {
  localStorage.setItem("hr_automation_token", tok);
  localStorage.setItem("hrms.locale", "en");
  localStorage.setItem("hrms.tours.seen", JSON.stringify(["setup", "settings"]));
  localStorage.setItem("hrms.pagetours.seen", JSON.stringify(["settings", "home"]));
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
async function step(name, fn) {
  try { await fn(); } catch (e) { log.push(`FAILED ${name}: ${String(e).split("\n")[0]}`); await page.screenshot({ path: join(SCR, `p23-3f-FAILED-${name}.png`) }).catch(() => {}); }
}
const messages = async () => (await (await page.request.get(`${MP}/api/v1/messages?limit=50`)).json()).messages ?? [];
async function emailShots(m, base) {
  for (const [suffix, width] of [["gmail", 1000], ["phone", 390]]) {
    const p2 = await ctx.newPage();
    await p2.setViewportSize({ width, height: 900 });
    await p2.goto(`${MP}/view/${m.ID}.html`, { waitUntil: "networkidle" });
    await p2.waitForTimeout(1500);  // banner GIF loads from the API (APP_BASE_URL)
    await p2.screenshot({ path: join(LET, `${base}-email-live-${suffix}.png`), fullPage: true });
    await p2.close();
  }
  const full = await (await page.request.get(`${MP}/api/v1/message/${m.ID}`)).json();
  writeFileSync(join(LET, `${base}-email-live.txt`), `Subject: ${m.Subject}\nTo: ${m.To.map((t) => t.Address).join(", ")}\n\n${full.Text ?? ""}`);
  log.push(`email ${base}: "${m.Subject}" text part ${String(full.Text ?? "").length} chars, html ${String(full.HTML ?? "").length} chars, attachments ${(full.Attachments ?? []).map((a) => a.FileName).join(", ") || "none"}`);
}

try {
  await step("email-design-page", async () => {
    await page.goto(BASE + "/settings/communication/email-design", { waitUntil: "load", timeout: 60000 });
    await page.waitForTimeout(3000); await settle();
    await page.screenshot({ path: join(SCR, "p23-3f-email-design.png"), fullPage: true });
    const before = (await messages()).length;
    await page.getByRole("button", { name: /Send test to me/ }).first().click();
    await page.waitForTimeout(3000);
    log.push(`UI "Send test to me": mailpit ${before} -> ${(await messages()).length}`);
    await page.screenshot({ path: join(SCR, "p23-3f-email-design-test-sent.png") });
  });
  await step("emails", async () => {
    for (const [key, base] of Object.entries(EMAILS)) {
      const r = await page.request.post(`${API}/api/v1/ui/design/emails/${key}/test`, auth);
      log.push(`test ${key}: HTTP ${r.status()} ${JSON.stringify(await r.json()).slice(0, 160)}`);
      await page.waitForTimeout(1500);
      const subj = { offer: /offer|selected|congrat/i, welcome: /welcome/i, "exit-letters": /relieving|experience|letters/i }[base];
      const m = (await messages()).find((x) => subj.test(x.Subject));
      if (m) await emailShots(m, base); else log.push(`email ${base}: NOT FOUND in mailpit`);
    }
  });
  await step("letters-page", async () => {
    await page.goto(BASE + "/settings/onboarding/letters", { waitUntil: "load", timeout: 60000 });
    await page.waitForTimeout(3500); await settle();
    await page.screenshot({ path: join(SCR, "p23-3f-letters-settings.png"), fullPage: true });
  });
  await step("letters", async () => {
    for (const kind of KINDS) {
      const r = await page.request.post(`${API}/api/v1/ui/design/letters/${kind}/preview`, { ...auth, data: { overrides: {} } });
      const buf = await r.body();
      writeFileSync(join(LET, `${kind}-letter-live.pdf`), buf);
      log.push(`letter ${kind}: HTTP ${r.status()} ${r.headers()["content-type"]} ${buf.length} bytes`);
    }
    const t = await page.request.post(`${API}/api/v1/ui/design/letters/offer/test`, auth);
    log.push(`letter test (offer): HTTP ${t.status()} ${JSON.stringify(await t.json()).slice(0, 160)}`);
    await page.waitForTimeout(1500);
    const m = (await messages())[0];
    const full = await (await page.request.get(`${MP}/api/v1/message/${m.ID}`)).json();
    log.push(`letter test email: "${m.Subject}" attachments ${(full.Attachments ?? []).map((a) => `${a.FileName} (${a.Size} B)`).join(", ") || "none"}`);
  });
} finally {
  console.log(log.join("\n"));
  await browser.close();
}
