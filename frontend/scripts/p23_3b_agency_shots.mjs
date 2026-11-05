// Part 23.3b: on-screen proof of 21.5 (agencies Recruitment / BGV / Both, edit, filter, stats, Excel import).
// env: SHOT_TOKEN, SHOT_CHROME, P23_DL (download folder), PHASE = A (create + edit) | B (stats, filter, import)
import { chromium } from "playwright";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "ui", "screens");
const BASE = "http://127.0.0.1:5174", API = "http://127.0.0.1:8010";
const { SHOT_TOKEN: TOKEN, PHASE = "A", P23_DL: DL, P23_IMPORT: IMPORT } = process.env;
if (!TOKEN) throw new Error("SHOT_TOKEN is required");

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
const shot = async (name, opts = {}) => { await page.screenshot({ path: join(OUT, `p23-3b-${name}.png`), ...opts }); log.push(`shot ${name}`); };
async function step(name, fn) {
  try { await fn(); } catch (e) { log.push(`FAILED ${name}: ${String(e).split("\n")[0]}`); await page.screenshot({ path: join(OUT, `p23-3b-FAILED-${name}.png`) }).catch(() => {}); await page.keyboard.press("Escape").catch(() => {}); }
}
const list = async (q = "") => (await (await page.request.get(`${API}/api/v1/agencies${q}`, auth)).json());
async function selectIn(dlg, label, option) {
  await dlg.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}
async function openCard(name) {
  await page.getByText(name, { exact: true }).first().click();
  await page.waitForLoadState("networkidle"); await page.waitForTimeout(800);
}

try {
  if (PHASE === "A") {
    await go("/agencies");
    await shot("list-before");
    const make = [
      { name: "Proof TalentReach (P23)", type: "Recruitment", person: "Proof Recruiter", email: "proof.talentreach.p23@example.com", fee: ["% of annual CTC", "8.33"], terms: "30 days after joining" },
      { name: "Proof SafeHire Checks (P23)", type: "BGV", person: "Proof Ops Desk", email: "proof.safehire.p23@example.com", checks: { Education: "800", Employment: "900", Address: "600" }, tat: "5", fmt: "One PDF per candidate" },
      { name: "Proof AllRound Partners (P23)", type: "Recruitment + BGV", person: "Proof Partner", email: "proof.allround.p23@example.com", fee: ["Fixed amount per hire", "40000"], checks: { Education: "700", Criminal: "1100" }, tat: "7" },
    ];
    for (const a of make) {
      await step(`create-${a.type}`, async () => {
        if ((await list()).some((x) => x.name === a.name)) { log.push(`exists ${a.name}`); return; }
        await page.getByRole("button", { name: "Add an agency" }).first().click();
        const dlg = page.getByRole("dialog");
        await dlg.getByLabel(/Agency name/).fill(a.name);
        await selectIn(dlg, "Type", a.type);
        await dlg.getByLabel("Contact person").fill(a.person);
        await dlg.getByLabel(/email/i).first().fill(a.email);
        await dlg.getByLabel("Phone").fill("+91 90000 23230");
        await dlg.getByRole("textbox", { name: "Address", exact: true }).fill("Proof address, Hyderabad");
        if (a.fee) {
          await selectIn(dlg, "Fee", a.fee[0]);
          await dlg.getByLabel(/^(Percent|Amount)$/).fill(a.fee[1]);
          if (a.terms) await dlg.getByLabel("Payment terms").fill(a.terms);
        }
        if (a.checks) {
          for (const [check, price] of Object.entries(a.checks)) {
            const box = page.getByRole("checkbox", { name: new RegExp(`^${check}`) });
            const row = dlg.locator("div").filter({ has: box }).filter({ has: page.getByLabel("Price") }).last();
            await row.getByRole("checkbox", { name: new RegExp(`^${check}`) }).check();
            await row.getByLabel("Price").fill(price);
          }
          await dlg.getByLabel(/Turnaround/).fill(a.tat);
          if (a.fmt) await dlg.getByLabel("Report format").fill(a.fmt);
        }
        await shot(`form-${a.type.replace(/\W+/g, "-").toLowerCase()}`, { fullPage: false });
        await dlg.getByRole("button", { name: "Add agency" }).click();
        await page.waitForLoadState("networkidle"); await page.waitForTimeout(1000);
        const row = (await list()).find((x) => x.name === a.name);
        log.push(`created ${a.name}: ${row ? `${row.agency_type} fee=${row.fee_type}/${row.fee_value} checks=${JSON.stringify(row.bgv_checks ?? row.bgv_checks_json)} tat=${row.turnaround_days}` : "NOT FOUND"}`);
      });
    }
    await step("edit", async () => {
      await go("/agencies");
      await openCard("Proof SafeHire Checks (P23)");
      await page.getByRole("button", { name: "Edit", exact: true }).first().click();
      const dlg = page.getByRole("dialog");
      await dlg.getByLabel(/Turnaround/).fill("4");
      await dlg.getByLabel(/GST/).fill("PROOF0000P23");
      await shot("edit-dialog");
      await dlg.getByRole("button", { name: "Save", exact: true }).click();
      await page.waitForLoadState("networkidle"); await page.waitForTimeout(1000);
      const row = (await list()).find((x) => x.name === "Proof SafeHire Checks (P23)");
      log.push(`after edit: tat=${row?.turnaround_days} gst=${row?.gst_pan}`);
      await shot("edited");
    });
  }
  if (PHASE === "B") {
    for (const [tab, file] of [["All", "filter-all"], ["Recruitment", "filter-recruitment"], ["BGV", "filter-bgv"]]) {
      await step(file, async () => {
        await go("/agencies");
        await page.getByRole("tab", { name: tab, exact: true }).click();
        await page.waitForLoadState("networkidle"); await page.waitForTimeout(800);
        const names = await page.getByText(/\(P23\)/).allInnerTexts();
        log.push(`${tab} tab shows: ${[...new Set(names)].join(", ")}`);
        await shot(file);
      });
    }
    for (const [name, file] of [["Proof TalentReach (P23)", "stats-recruitment"], ["Proof SafeHire Checks (P23)", "stats-bgv"], ["Proof AllRound Partners (P23)", "stats-both"]]) {
      await step(file, async () => {
        await go("/agencies");
        await openCard(name);
        const id = (await list()).find((x) => x.name === name)?.id;
        const d = await (await page.request.get(`${API}/api/v1/agencies/${id}`, auth)).json();
        log.push(`${name} stats: ${JSON.stringify(d.stats)}`);
        await shot(file);
      });
    }
    await step("sample", async () => {
      await go("/agencies");
      const [d] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Sample import file" }).click()]);
      await d.saveAs(join(DL, "agencies-import-sample.xlsx"));
      log.push(`sample downloaded: ${d.suggestedFilename()}`);
    });
    if (IMPORT) await step("import", async () => {
      await go("/agencies");
      await page.locator("input[type=file][accept='.xlsx']").setInputFiles(IMPORT);
      await page.waitForLoadState("networkidle"); await page.waitForTimeout(1500);
      await shot("import-result");
      const rows = (await list()).filter((x) => /Proof Import/.test(x.name));
      log.push(`imported: ${rows.map((r) => `${r.name} (${r.agency_type}, checks ${JSON.stringify(r.bgv_checks ?? r.bgv_checks_json)})`).join(" | ")}`);
    });
  }
} finally {
  console.log(log.join("\n"));
  await browser.close();
}
