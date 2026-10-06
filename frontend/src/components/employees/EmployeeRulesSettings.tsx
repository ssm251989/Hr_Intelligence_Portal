// Part 20.5: Settings > Onboarding & employees > Employee rules -- one plain-language page for the employee
// settings that had no screen: company email, what happens when onboarding completes, roles for new employees,
// interviewers (auto rule + scorecard reminder), notice period by employment type, who approves a resignation.
// Employee ID, joining details, exit interview, exit checklist and letters have their own pages next to this one.
import { useEffect, useState, type ReactNode } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Radio from "@mui/material/Radio";
import RadioGroup from "@mui/material/RadioGroup";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";

import { extractErrorMessage, platformSettingsApi } from "../../api/client";
import { useT } from "../../i18n";

type Rule = { field: "designation" | "department"; contains: string; role?: string };
interface State {
  domain: string; pattern: string; fallbacks: string; onComplete: "approve" | "automatic"; defaultRoles: string[]; roleRules: Rule[];
  autoRules: Rule[]; reminderHours: number; notice: Record<string, number>; steps: "manager_hr" | "hr";
}
const ROLES = ["Employee", "Interviewer", "Manager", "Hiring Manager"];
const PATTERNS = ["{first}.{last}", "{first}{last}", "{f}{last}", "{first}.{l}", "{first}"];

function Section({ title, hint, children }: { title: string; hint: string; children: ReactNode }) {
  return (
    <Card variant="outlined" sx={{ p: 2 }}>
      <Typography component="h3" sx={{ fontWeight: 800 }}>{title}</Typography>
      <Typography sx={{ fontSize: 13, color: "text.secondary", mb: 1.5 }}>{hint}</Typography>
      {children}
    </Card>
  );
}

function RuleRows({ rules, withRole, onChange }: { rules: Rule[]; withRole?: boolean; onChange: (r: Rule[]) => void }) {
  const t = useT();
  const set = (i: number, p: Partial<Rule>) => onChange(rules.map((r, j) => (j === i ? { ...r, ...p } : r)));
  return (
    <Stack spacing={1}>
      {rules.map((r, i) => (
        <Stack key={i} direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
          <TextField select size="small" label={t("er.if")} value={r.field} onChange={(e) => set(i, { field: e.target.value as Rule["field"] })} sx={{ minWidth: 160 }}>
            <MenuItem value="designation">{t("er.designation")}</MenuItem>
            <MenuItem value="department">{t("er.department")}</MenuItem>
          </TextField>
          <TextField size="small" label={t("er.contains")} value={r.contains} onChange={(e) => set(i, { contains: e.target.value })} sx={{ flex: 1 }} />
          {withRole && (
            <TextField select size="small" label={t("er.give_role")} value={r.role ?? "Interviewer"} onChange={(e) => set(i, { role: e.target.value })} sx={{ minWidth: 170 }}>
              {ROLES.filter((x) => x !== "Employee").map((x) => <MenuItem key={x} value={x}>{x}</MenuItem>)}
            </TextField>
          )}
          <IconButton aria-label={t("er.remove")} onClick={() => onChange(rules.filter((_, j) => j !== i))}><DeleteOutlineIcon /></IconButton>
        </Stack>
      ))}
      <Box><Button size="small" onClick={() => onChange([...rules, { field: "designation", contains: "", ...(withRole ? { role: "Interviewer" } : {}) }])}>{t("er.add_rule")}</Button></Box>
    </Stack>
  );
}

export default function EmployeeRulesSettings() {
  const t = useT();
  const [s, setS] = useState<State | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([platformSettingsApi.definitions(), platformSettingsApi.values()]).then(([defs, vals]) => {
      const v = (k: string) => {
        const row = vals.find((x) => x.key === k && x.scope_type === "tenant");
        return row ? row.value : defs.find((d) => d.key === k)?.default;
      };
      const steps = (v("employees.exit.approval_steps") as string[] | undefined) ?? ["manager", "hr"];
      setS({
        domain: (v("employees.email.domain") as string) ?? "", pattern: (v("employees.email.pattern") as string) ?? "{first}.{last}",
        fallbacks: ((v("employees.email.fallbacks") as string[]) ?? []).join(", "),
        onComplete: (v("employees.on_onboarding_complete") as State["onComplete"]) ?? "approve",
        defaultRoles: (v("employees.default_roles") as string[]) ?? ["Employee"], roleRules: (v("employees.role_rules") as Rule[]) ?? [],
        autoRules: (v("employees.interviewer.auto_rules") as Rule[]) ?? [], reminderHours: Number(v("employees.interviewer.scorecard_reminder_hours") ?? 24),
        notice: (v("employees.notice_days") as Record<string, number>) ?? {}, steps: steps.includes("manager") ? "manager_hr" : "hr",
      });
    }).catch((e) => setMsg({ ok: false, text: extractErrorMessage(e, "") }));
  }, []);

  if (!s) return msg ? <Alert severity="error">{msg.text}</Alert> : <Skeleton variant="rounded" height={400} />;
  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const clean = (rules: Rule[]) => rules.filter((r) => r.contains.trim()).map((r) => ({ ...r, contains: r.contains.trim() }));
      const values: [string, unknown][] = [
        ["employees.email.domain", s.domain.trim().replace(/^@/, "")], ["employees.email.pattern", s.pattern.trim() || "{first}.{last}"],
        ["employees.email.fallbacks", s.fallbacks.split(",").map((x) => x.trim()).filter(Boolean)], ["employees.on_onboarding_complete", s.onComplete],
        ["employees.default_roles", Array.from(new Set(["Employee", ...s.defaultRoles]))], ["employees.role_rules", clean(s.roleRules)],
        ["employees.interviewer.auto_rules", clean(s.autoRules).map(({ field, contains }) => ({ field, contains }))],
        ["employees.interviewer.scorecard_reminder_hours", Math.min(240, Math.max(1, Math.round(s.reminderHours) || 24))],
        ["employees.notice_days", Object.fromEntries(Object.entries(s.notice).map(([k, n]) => [k, Math.max(0, Math.round(Number(n)) || 0)]))],
        ["employees.exit.approval_steps", s.steps === "manager_hr" ? ["manager", "hr"] : ["hr"]],
      ];
      for (const [k, v] of values) await platformSettingsApi.update(k, v);
      setMsg({ ok: true, text: t("er.saved") });
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, "") });
    } finally {
      setBusy(false);
    }
  };
  const example = s.pattern.replace("{first}", "kishore").replace("{last}", "gunda").replace("{f}", "k").replace("{l}", "g") + "@" + (s.domain || "ctdtechs.com");

  return (
    <Stack spacing={2} data-testid="employee-rules">
      <Typography color="text.secondary">{t("er.intro")}</Typography>
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}

      <Section title={t("er.email.title")} hint={t("er.email.hint")}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
          <TextField label={t("er.email.domain")} placeholder="ctdtechs.com" value={s.domain} onChange={(e) => setS({ ...s, domain: e.target.value })} />
          <TextField select label={t("er.email.pattern")} value={PATTERNS.includes(s.pattern) ? s.pattern : "custom"} sx={{ minWidth: 200 }}
            onChange={(e) => setS({ ...s, pattern: e.target.value === "custom" ? s.pattern : e.target.value })}>
            {PATTERNS.map((p) => <MenuItem key={p} value={p}>{p}</MenuItem>)}
            {!PATTERNS.includes(s.pattern) && <MenuItem value="custom">{s.pattern}</MenuItem>}
          </TextField>
          <TextField label={t("er.email.fallbacks")} value={s.fallbacks} onChange={(e) => setS({ ...s, fallbacks: e.target.value })} sx={{ flex: 1 }} helperText={t("er.email.fallbacks_hint")} />
        </Stack>
        <Typography sx={{ fontSize: 13, mt: 1 }}>{t("er.email.example", { address: example })}</Typography>
      </Section>

      <Section title={t("er.complete.title")} hint={t("er.complete.hint")}>
        <RadioGroup value={s.onComplete} onChange={(e) => setS({ ...s, onComplete: e.target.value as State["onComplete"] })}>
          <FormControlLabel value="approve" control={<Radio />} label={t("er.complete.approve")} />
          <FormControlLabel value="automatic" control={<Radio />} label={t("er.complete.automatic")} />
        </RadioGroup>
      </Section>

      <Section title={t("er.roles.title")} hint={t("er.roles.hint")}>
        <Stack direction="row" flexWrap="wrap" useFlexGap>
          {ROLES.map((r) => (
            <FormControlLabel key={r} label={r} control={<Checkbox checked={r === "Employee" || s.defaultRoles.includes(r)} disabled={r === "Employee"}
              onChange={(e) => setS({ ...s, defaultRoles: e.target.checked ? [...s.defaultRoles, r] : s.defaultRoles.filter((x) => x !== r) })} />} />
          ))}
        </Stack>
        <Typography sx={{ fontWeight: 700, mt: 1, mb: 1 }}>{t("er.roles.rules")}</Typography>
        <RuleRows rules={s.roleRules} withRole onChange={(roleRules) => setS({ ...s, roleRules })} />
      </Section>

      <Section title={t("er.iv.title")} hint={t("er.iv.hint")}>
        <RuleRows rules={s.autoRules} onChange={(autoRules) => setS({ ...s, autoRules })} />
        <TextField type="number" label={t("er.iv.reminder")} value={s.reminderHours} onChange={(e) => setS({ ...s, reminderHours: Number(e.target.value) })}
          inputProps={{ min: 1, max: 240 }} sx={{ mt: 2, maxWidth: 320 }} helperText={t("er.iv.reminder_hint")} />
      </Section>

      <Section title={t("er.notice.title")} hint={t("er.notice.hint")}>
        <Box sx={{ display: "grid", gap: 1, gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(3, 1fr)" } }}>
          {Object.entries(s.notice).map(([k, n]) => (
            <TextField key={k} type="number" label={t(`er.notice.${k}`) === `er.notice.${k}` ? k : t(`er.notice.${k}`)} value={n} inputProps={{ min: 0, max: 365 }}
              onChange={(e) => setS({ ...s, notice: { ...s.notice, [k]: Number(e.target.value) } })} />
          ))}
        </Box>
      </Section>

      <Section title={t("er.exit.title")} hint={t("er.exit.hint")}>
        <RadioGroup value={s.steps} onChange={(e) => setS({ ...s, steps: e.target.value as State["steps"] })}>
          <FormControlLabel value="manager_hr" control={<Radio />} label={t("er.exit.manager_hr")} />
          <FormControlLabel value="hr" control={<Radio />} label={t("er.exit.hr")} />
        </RadioGroup>
        <Typography sx={{ fontSize: 13, color: "text.secondary" }}>{t("er.exit.more")}</Typography>
      </Section>

      <Box><Button variant="contained" onClick={save} disabled={busy}>{t("er.save")}</Button></Box>
    </Stack>
  );
}
