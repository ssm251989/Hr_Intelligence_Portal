// Part 23.3a: on-screen proof of 21.4 (BGV Download all + BGV vendor) on the proof stack.
// env: SHOT_TOKEN (temp admin, never stored), SHOT_CHROME, P23_JOB, P23_APP1, P23_APP2, PHASE = A | B | C, P23_DL (download folder)
// A: Download all (card + bulk), assign vendor to candidate 1, vendor opens link + uploads report, HR sees it, discrepancy decision
// B: assign vendor to candidate 2 with due date tomorrow (reminder is then run from the backend script)
// C: reassign candidate 2 to the second vendor, then cancel; mailpit inbox shots
import { chromium } from "playwright";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { writeFileSync } from "node:fs";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "ui", "screens");
const BASE = "http://127.0.0.1:5174", API = "http://127.0.0.1:8010", MP = "http://127.0.0.1:8025";
const { SHOT_TOKEN: TOKEN, P23_JOB: JOB, P23_APP1: APP1, P23_APP2: APP2, PHASE = "A", P23_DL: DL } = process.env;
if (!TOKEN || !JOB || !APP1 || !APP2) throw new Error("SHOT_TOKEN, P23_JOB, P23_APP1, P23_APP2 are required");

const browser = await chromium.launch(process.env.SHOT_CHROME ? { executablePath: process.env.SHOT_CHROME } : {});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light", reducedMotion: "reduce", acceptDownloads: true });
await ctx.addInitScript((tok) => {
  localStorage.setItem("hr_automation_token", tok);
  localStorage.setItem("hrms.locale", "en");
  localStorage.setItem("hrms.tours.seen", JSON.stringify(["setup", "inbox", "reports", "settings", "hiring"]));
  localStorage.setItem("hrms.pagetours.seen", JSON.stringify(["settings", "bgv", "agencies", "inbox", "employees", "finance"]));
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
const shot = async (name, opts = {}) => { await page.screenshot({ path: join(OUT, `p23-3a-${name}.png`), ...opts }); log.push(`shot ${name}`); };
async function step(name, fn) {
  if (process.env.P23_ONLY && !process.env.P23_ONLY.split(",").includes(name)) return;
  try { await fn(); } catch (e) { log.push(`FAILED ${name}: ${String(e).split("\n")[0]}`); await page.screenshot({ path: join(OUT, `p23-3a-FAILED-${name}.png`) }).catch(() => {}); }
}
const assignments = async (app) => (await (await page.request.get(`${API}/api/v1/ui/bgv/${app}/assignments`, auth)).json());
const NAME = { [APP1]: "Proof Ananya Rao", [APP2]: "Proof Vikram Sethi" };
const idxOf = (app) => app;  // cards are found by the candidate's name (the page re-orders them by status)
// innermost block holding both the candidate's name and a vendor card = that candidate's card
const box = (app) => page.locator("div").filter({ has: page.getByText(NAME[app], { exact: true }) })
  .filter({ has: page.getByText("Background check vendor", { exact: true }) }).last();
const card = (app) => box(app).getByText("Background check vendor", { exact: true });
async function openApp(app) { await go(`/bgv?jobId=${JOB}&application=${app}`); await card(idxOf(app)).scrollIntoViewIfNeeded(); await page.waitForTimeout(600); }
async function mailpit() { return (await (await page.request.get(`${MP}/api/v1/messages?limit=50`)).json()).messages ?? []; }
async function mailShot(subjectRe, name) {
  const m = (await mailpit()).find((x) => subjectRe.test(x.Subject));
  if (!m) { log.push(`mail NOT FOUND ${subjectRe}`); return null; }
  log.push(`mail "${m.Subject}" -> ${m.To.map((t) => t.Address).join(", ")}`);
  const p2 = await ctx.newPage();
  await p2.goto(`${MP}/view/${m.ID}`, { waitUntil: "networkidle" });
  await p2.waitForTimeout(800);
  await p2.screenshot({ path: join(OUT, `p23-3a-${name}.png`) });
  await p2.close();
  log.push(`shot ${name}`);
  return (await (await page.request.get(`${MP}/api/v1/message/${m.ID}`)).json());
}
async function assignVia(vendorName, dueISO, i = APP1) {
  const btn = box(i).getByRole("button", { name: /^(Assign BGV vendor|Reassign)$/ }).first();
  await btn.click();
  const dlg = page.getByRole("dialog");
  await dlg.getByRole("combobox", { name: "Vendor" }).click();
  await page.getByRole("option", { name: vendorName }).click();
  if (dueISO) await dlg.getByLabel(/Due/).fill(dueISO);
  await page.waitForTimeout(400);
}

try {
  if (PHASE === "A") {
    await step("stage-table", async () => {
      await go(`/bgv?jobId=${JOB}`);
      await shot("bgv-page", { fullPage: true });
    });
    await step("download-card", async () => {
      await openApp(APP1);
      await shot("vendor-card-empty");
      const [d] = await Promise.all([page.waitForEvent("download"), box(APP1).getByRole("button", { name: "Download all documents" }).click()]);
      const p = join(DL, "card-" + d.suggestedFilename());
      await d.saveAs(p);
      log.push(`card download: ${d.suggestedFilename()} -> ${p}`);
    });
    await step("download-bulk", async () => {
      await go(`/bgv?jobId=${JOB}`);
      for (const n of ["Proof Ananya Rao", "Proof Vikram Sethi"]) {
        await page.getByRole("row").filter({ hasText: n }).getByRole("checkbox").first().check();
      }
      await page.waitForTimeout(400);
      await shot("bulk-bar");
      const [d] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: /^Download all \(2\)$/ }).click()]);
      const p = join(DL, "bulk-" + d.suggestedFilename());
      await d.saveAs(p);
      log.push(`bulk download: ${d.suggestedFilename()} -> ${p}`);
    });
    let link = null;
    await step("assign", async () => {
      await openApp(APP1);
      await assignVia("Proof Verify Co (P23)");
      // two checks only
      const dlg = page.getByRole("dialog");
      for (const c of [/^Address/, /^Criminal record/]) await dlg.getByLabel(c).uncheck();
      await shot("assign-dialog");
      await dlg.getByRole("button", { name: "Assign and email the vendor" }).click();
      await page.waitForLoadState("networkidle"); await page.waitForTimeout(1200);
      await card(APP1).scrollIntoViewIfNeeded();
      await shot("assigned");
      const a = (await assignments(APP1)).items[0];
      log.push(`assignment: status=${a.status} checks=${a.checks} due=${a.due_date} cost=${a.cost}`);
      const m = await mailShot(/Proof Ananya Rao/, "mail-assigned");
      link = (m?.Text ?? "").match(/https?:\/\/\S*bgv-vendor\/[\w-]+/)?.[0] ?? null;
      log.push(`vendor link from email: ${link ? link.replace(/[\w-]{20,}$/, "<token>") : "none"}`);
    });
    await step("vendor-page", async () => {
      if (!link) throw new Error("no link");
      const v = await ctx.newPage();
      await v.goto(link, { waitUntil: "networkidle" });
      await v.waitForTimeout(800);
      await v.screenshot({ path: join(OUT, "p23-3a-vendor-page.png"), fullPage: true });
      log.push(`after open: ${(await assignments(APP1)).items[0].status}`);
      const rep = join(DL, "Proof Verify Co - BGV report - Ananya Rao.pdf");
      writeFileSync(rep, "%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n");
      await v.locator("input[type=file]").setInputFiles(rep);
      await v.getByLabel(/note/i).fill("Education verified. Employment: last employer confirmed dates, designation differs (Analyst vs Senior Analyst).");
      await v.screenshot({ path: join(OUT, "p23-3a-vendor-upload.png"), fullPage: true });
      await v.getByRole("button", { name: /^Upload/ }).click();
      await v.waitForLoadState("networkidle"); await v.waitForTimeout(1200);
      await v.screenshot({ path: join(OUT, "p23-3a-vendor-uploaded.png"), fullPage: true });
      log.push(`after upload: ${(await assignments(APP1)).items[0].status}`);
      await v.close();
    });
    await step("hr-notified", async () => {
      await openApp(APP1);
      await shot("report-received");
      await page.getByRole("button", { name: /notification/i }).first().click().catch(() => page.locator("header button").nth(2).click());
      await page.waitForTimeout(1000);
      await shot("hr-notice");
      await page.keyboard.press("Escape");
    });
    await step("discrepancy", async () => {
      await openApp(APP1);
      await page.getByRole("button", { name: "Discrepancy - clear with a note" }).first().click();
      const dlg = page.getByRole("dialog");
      await dlg.getByRole("textbox").first().fill("Designation on the experience letter is Analyst, the resume says Senior Analyst. Same employer and dates - accepted.");
      await shot("discrepancy-dialog");
      await dlg.getByRole("button", { name: /Clear with this note/ }).click();
      await page.waitForLoadState("networkidle"); await page.waitForTimeout(1500);
      await shot("discrepancy-done", { fullPage: true });
      const s = await assignments(APP1);
      log.push(`after discrepancy: application=${s.status} assignment=${s.items[0].status}/${s.items[0].decision}`);
    });
  }
  if (PHASE === "B") {
    await step("assign2", async () => {
      await openApp(APP2);
      await shot("vendor-card-empty");
      const t = new Date(); t.setDate(t.getDate() + 1);
      await assignVia("Proof Verify Co (P23)", t.toISOString().slice(0, 10), APP2);
      await page.getByRole("dialog").getByRole("button", { name: "Assign and email the vendor" }).click();
      await page.waitForLoadState("networkidle"); await page.waitForTimeout(1200);
      const a = (await assignments(APP2)).items[0];
      log.push(`candidate 2 assignment: status=${a.status} due=${a.due_date}`);
    });
  }
  if (PHASE === "C") {
    await step("reminder", async () => {
      await openApp(APP2);
      await shot("reminder-on-card");
      await mailShot(/remind|due/i, "mail-reminder");
    });
    await step("reassign", async () => {
      await openApp(APP2);
      await assignVia("Proof Second Checks (P23)", null, APP2);
      await shot("reassign-dialog");
      await page.getByRole("dialog").getByRole("button", { name: "Assign and email the vendor" }).click();
      await page.waitForLoadState("networkidle"); await page.waitForTimeout(1200);
      await card(APP2).scrollIntoViewIfNeeded();
      await shot("reassigned");
      const s = await assignments(APP2);
      log.push(`after reassign: ${s.items.map((a) => `${a.agency}:${a.status}${a.cancel_reason ? ` (${a.cancel_reason})` : ""}`).join(" | ")}`);
    });
    await step("cancel", async () => {
      await box(APP2).getByRole("button", { name: "Cancel assignment" }).click();
      const dlg = page.getByRole("dialog");
      await dlg.getByRole("textbox").fill("Candidate withdrew - no checks needed.");
      await dlg.getByRole("button", { name: "Cancel and tell the vendor" }).click();
      await page.waitForLoadState("networkidle"); await page.waitForTimeout(1200);
      await card(APP2).scrollIntoViewIfNeeded();
      await shot("cancelled");
      const s = await assignments(APP2);
      log.push(`after cancel: ${s.items.map((a) => `${a.agency}:${a.status}${a.cancel_reason ? ` (${a.cancel_reason})` : ""}`).join(" | ")}`);
    });
    await step("mails", async () => {
      await mailShot(/Proof Vikram Sethi/i, "mail-latest-vikram");
      for (const m of await mailpit()) log.push(`mailpit: ${m.Created?.slice(11, 19)} "${m.Subject}" -> ${m.To.map((t) => t.Address).join(", ")}`);
      const p2 = await ctx.newPage();
      await p2.goto(MP, { waitUntil: "networkidle" }); await p2.waitForTimeout(800);
      await p2.screenshot({ path: join(OUT, "p23-3a-mailpit-inbox.png") });
      await p2.close();
    });
  }
} finally {
  console.log(log.join("\n"));
  await browser.close();
}
