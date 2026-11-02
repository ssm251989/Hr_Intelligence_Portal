// Part 23.3d: on-screen proof of 22.1 (HR assistant): the 10 verification questions from PART22 22.1 step 6,
// one screenshot each, answers + sources logged; the "not in the handbook" question is handed over to HR.
// env: SHOT_TOKEN, SHOT_CHROME. The API runs the committed code (HEAD worktree), real model (Anthropic).
import { chromium } from "playwright";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { writeFileSync } from "node:fs";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "ui", "screens");
const BASE = "http://127.0.0.1:5174";
const TOKEN = process.env.SHOT_TOKEN;
if (!TOKEN) throw new Error("SHOT_TOKEN is required");
const QUESTIONS = [
  ["casual-leave", "How many casual leaves do I get?"],
  ["notice-senior", "What is the notice period for a senior employee?"],
  ["wfh", "Can I work from home?"],
  ["salary-date", "When is salary credited?"],
  ["hotel-junior-metro", "Hotel limit for a junior employee in a metro city?"],
  ["probation", "How long is probation?"],
  ["open-jobs", "How many open jobs do we have?"],
  ["waiting-interview", "Which candidates are waiting for an interview?"],
  ["eg1", "Eg1"],
  ["not-in-handbook", "Is there a company policy on bringing pets to the office?"],
];

const browser = await chromium.launch(process.env.SHOT_CHROME ? { executablePath: process.env.SHOT_CHROME } : {});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light", reducedMotion: "reduce" });
await ctx.addInitScript((tok) => {
  localStorage.setItem("hr_automation_token", tok);
  localStorage.setItem("hrms.locale", "en");
  localStorage.setItem("hrms.tours.seen", JSON.stringify(["setup", "inbox", "reports", "settings", "hiring"]));
  localStorage.setItem("hrms.pagetours.seen", JSON.stringify(["home", "settings", "inbox"]));
}, TOKEN);
const page = await ctx.newPage();
const log = [], answers = [];

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

try {
  await page.goto(BASE + "/", { waitUntil: "load", timeout: 60000 }); await page.waitForTimeout(4000);
  await settle();
  await page.getByRole("button", { name: "Open assistant" }).click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: join(OUT, "p23-3d-00-open.png") });
  let n = 0;
  for (const [key, q] of QUESTIONS) {
    n++;
    if (process.env.P23_ONLY && !process.env.P23_ONLY.split(",").includes(key)) continue;
    try {
      const box = page.getByRole("textbox", { name: "Your question" });
      await box.fill(q);
      const resp = page.waitForResponse((r) => r.url().endsWith("/api/v1/intelligence/copilot/ask"), { timeout: 120000 });
      await page.getByRole("button", { name: "Send" }).click();
      const r = await resp;
      const body = await r.json().catch(() => ({}));
      await page.waitForTimeout(1500);
      const cites = (body.citations ?? body.citations_json ?? []).map((c) => c.title ?? c.source ?? c.document ?? JSON.stringify(c).slice(0, 80));
      const a = { n, key, question: q, http: r.status(), answer: String(body.answer ?? body.text ?? body.detail ?? "").replace(/\s+/g, " "),
        sources: cites, clarify: !!body.clarify, suggestions: body.suggestions ?? null, draft: body.draft ? { id: body.draft.id, action: body.draft.action, summary: body.draft.summary } : null,
        confidence: body.confidence ?? null };
      answers.push(a);
      log.push(`${String(n).padStart(2, "0")} ${q} -> HTTP ${a.http} | ${a.answer.slice(0, 220)}${a.sources.length ? ` | sources: ${a.sources.join("; ")}` : ""}${a.draft ? ` | draft ${a.draft.action}` : ""}`);
      await page.screenshot({ path: join(OUT, `p23-3d-${String(n).padStart(2, "0")}-${key}.png`) });
      if (key === "not-in-handbook" && a.draft) {
        const confirmBtn = page.getByRole("button", { name: /^(Confirm|Hand over to HR)/ }).last();
        const done = page.waitForResponse((r2) => r2.url().includes(`/copilot/drafts/${a.draft.id}/confirm`), { timeout: 60000 });
        await confirmBtn.click();
        const c = await (await done).json().catch(() => ({}));
        log.push(`   hand-over confirmed: ${JSON.stringify(c).slice(0, 300)}`);
        await page.waitForTimeout(1500);
        await page.screenshot({ path: join(OUT, `p23-3d-${String(n).padStart(2, "0")}-${key}-handed-over.png`) });
        // the HR to-do in My approvals + the email to the HR mailbox (mailpit)
        await page.goto(BASE + "/approvals", { waitUntil: "load", timeout: 60000 }); await page.waitForTimeout(3500); await settle();
        await page.screenshot({ path: join(OUT, "p23-3d-11-hr-todo-in-approvals.png") });
        const msgs = (await (await page.request.get("http://127.0.0.1:8025/api/v1/messages?limit=20")).json()).messages ?? [];
        const m = msgs.find((x) => /question|assistant|hand/i.test(x.Subject));
        log.push(`   mailpit: ${m ? `"${m.Subject}" -> ${m.To.map((t) => t.Address).join(", ")}` : "NO hand-over email"}`);
        if (m) {
          const p2 = await ctx.newPage();
          await p2.goto(`http://127.0.0.1:8025/view/${m.ID}`, { waitUntil: "networkidle" }); await p2.waitForTimeout(800);
          await p2.screenshot({ path: join(OUT, "p23-3d-12-handover-email.png") });
          await p2.close();
        }
      }
    } catch (e) {
      log.push(`FAILED ${key}: ${String(e).split("\n")[0]}`);
      await page.screenshot({ path: join(OUT, `p23-3d-FAILED-${key}.png`) }).catch(() => {});
    }
  }
} finally {
  if (process.env.P23_ANSWERS) writeFileSync(process.env.P23_ANSWERS, JSON.stringify(answers, null, 1));
  console.log(log.join("\n"));
  await browser.close();
}
