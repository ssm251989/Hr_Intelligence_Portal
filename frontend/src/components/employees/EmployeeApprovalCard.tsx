import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import FormControlLabel from "@mui/material/FormControlLabel";
import MenuItem from "@mui/material/MenuItem";
import Radio from "@mui/material/Radio";
import RadioGroup from "@mui/material/RadioGroup";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { employeesApi, type AgentCard, type EmployeeFacets, type ItTodo } from "../../api/employeesApi";
import { useT } from "../../i18n";
import { Emoji, StatusChip } from "../../ui-kit";

// Part 20.2: the Onboarding agent's approval card -- everything it will create (Employee ID, record,
// company email, app account + roles), editable before "Approve". A failed step shows in plain words
// with Retry. A provider's first password is shown ONCE here and never stored.

const ROLE_CHOICES = ["Employee", "Interviewer", "Manager", "Hiring Manager", "Recruiter", "HR Admin"];
const STEP_KEYS: Record<string, string> = {
  link_existing: "emp.card.step.link_existing", employee_record: "emp.card.step.employee_record", company_email: "emp.card.step.company_email", app_account: "emp.card.step.app_account",
};

export function EmployeeApprovalCard({ card, facets, onChanged, highlight }: { card: AgentCard; facets: EmployeeFacets | null; onChanged: () => void; highlight?: boolean }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const p = card.plan;
  const [form, setForm] = useState({
    first_name: p.first_name, last_name: p.last_name, designation: p.designation ?? "", department_id: p.department_id ?? "", location_id: p.location_id ?? "",
    employment_type: p.employment_type, joined_on: p.joined_on, company_email: p.company_email ?? "",
    previous_years: p.previous_experience_months != null ? String(Math.round((p.previous_experience_months / 12) * 10) / 10) : "",
  });
  const [roles, setRoles] = useState<string[]>(p.roles);
  const [decision, setDecision] = useState<string>(p.match_decision ?? "");
  const [emailCheck, setEmailCheck] = useState<{ free: boolean; why: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [oneTime, setOneTime] = useState<string | null>(null);
  const failed = (p.steps ?? []).filter((s) => !s.ok);

  useEffect(() => {
    if (!form.company_email) { setEmailCheck(null); return undefined; }
    const id = window.setTimeout(() => {
      employeesApi.checkEmail(form.company_email, p.employee_id).then((r) => setEmailCheck({ free: r.free, why: r.why })).catch(() => setEmailCheck(null));
    }, 500);
    return () => window.clearTimeout(id);
  }, [form.company_email, p.employee_id]);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((s) => ({ ...s, [k]: e.target.value }));
  const approve = async () => {
    setBusy(true);
    setError(null);
    try {
      const { previous_years, ...rest } = form;
      const r = await employeesApi.approve(card.id, {
        ...rest, roles, match_decision: decision || undefined,
        previous_experience_months: previous_years === "" ? null : Math.round(Number(previous_years) * 12),
      });
      if (r.one_time_password) setOneTime(r.one_time_password);
      else onChanged();
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    } finally {
      setBusy(false);
    }
  };
  const later = async () => { setBusy(true); try { await employeesApi.reject(card.id); onChanged(); } finally { setBusy(false); } };
  const providerChip = p.email_provider === "it_todo" ? t("emp.card.mail_it") : p.email_provider === "test" ? t("emp.card.mail_test") : t("emp.card.mail_real", { provider: p.email_provider });

  if (oneTime) {
    return (
      <Card sx={{ p: 2, border: `2px solid ${f.sun}` }}>
        <Alert severity="warning" sx={{ mb: 1.5 }}>{t("emp.card.one_time")}</Alert>
        <Typography sx={{ fontFamily: "monospace", fontSize: 20, fontWeight: 700, my: 1 }} data-testid="one-time-password">{oneTime}</Typography>
        <Button variant="contained" onClick={() => { setOneTime(null); onChanged(); }}>{t("emp.card.one_time_done")}</Button>
      </Card>
    );
  }

  return (
    <Card data-testid="employee-approval-card" sx={{ p: { xs: 1.5, md: 2 }, border: `2px solid ${highlight ? f.brand : f.line}` }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
        <Emoji name="robot" size={22} />
        <Typography sx={{ fontWeight: 800, flex: 1 }}>{t("emp.card.title", { name: `${p.first_name} ${p.last_name}`.trim(), code: p.employee_code })}</Typography>
        {failed.length > 0 ? <StatusChip tone="coral" emoji="warning" label={t("emp.card.failed_steps", { n: failed.length })} />
          : <StatusChip tone="sun" emoji="hourglass" label={t("emp.card.waiting")} />}
      </Stack>
      <Typography sx={{ fontSize: 13, color: f.muted, mb: 1.5 }}>{t("emp.card.intro", { job: p.job_title ?? "", date: new Date(`${p.joined_on}T00:00:00`).toLocaleDateString() })}</Typography>

      {p.match && (
        <Alert severity={p.match.kind === "exact" ? "info" : "warning"} sx={{ mb: 1.5 }}>
          {p.match.kind === "exact" ? t("emp.card.match_exact", { code: p.match.code, name: p.match.name, reason: p.match.reason }) : (
            <>
              <strong>{t("emp.card.match_q", { code: p.match.code, name: p.match.name })}</strong> ({p.match.reason})
              <RadioGroup row value={decision} onChange={(e) => setDecision(e.target.value)}>
                <FormControlLabel value="same" control={<Radio size="small" />} label={t("emp.card.same")} />
                <FormControlLabel value="different" control={<Radio size="small" />} label={t("emp.card.different")} />
              </RadioGroup>
            </>
          )}
        </Alert>
      )}

      <Box sx={{ display: "grid", gap: 1.25, gridTemplateColumns: { xs: "1fr", md: "1fr 1fr 1fr" } }}>
        <TextField size="small" label={t("emp.col.code")} value={p.employee_code} disabled helperText={t("emp.edit.code_hint")} />
        <TextField size="small" label={t("emp.edit.first_name")} value={form.first_name} onChange={set("first_name")} />
        <TextField size="small" label={t("emp.edit.last_name")} value={form.last_name} onChange={set("last_name")} />
        <TextField size="small" label={t("emp.col.designation")} value={form.designation} onChange={set("designation")} />
        <TextField size="small" select label={t("emp.col.department")} value={form.department_id} onChange={set("department_id")}
          helperText={!p.department_matched && p.department ? t("emp.card.not_matched", { value: p.department }) : undefined}>
          <MenuItem value="">—</MenuItem>
          {(facets?.departments ?? []).map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
        </TextField>
        <TextField size="small" select label={t("emp.col.location")} value={form.location_id} onChange={set("location_id")}
          helperText={!p.location_matched && p.location ? t("emp.card.not_matched", { value: p.location }) : undefined}>
          <MenuItem value="">—</MenuItem>
          {(facets?.locations ?? []).map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
        </TextField>
        <TextField size="small" label={t("emp.col.manager")} value={p.manager ?? "—"} disabled helperText={p.manager ? undefined : t("emp.card.manager_later")} />
        <TextField size="small" select label={t("emp.col.type")} value={form.employment_type} onChange={set("employment_type")}>
          {["full_time", "part_time", "contract", "intern", "consultant"].map((k) => <MenuItem key={k} value={k}>{t(`emp.type.${k}`)}</MenuItem>)}
        </TextField>
        <TextField size="small" type="date" label={t("emp.col.joined")} value={form.joined_on} onChange={set("joined_on")} InputLabelProps={{ shrink: true }} />
        <TextField size="small" type="number" label={t("emp.edit.previous_years")} value={form.previous_years} onChange={set("previous_years")} helperText={t("emp.card.from_resume")} />
        <Box sx={{ gridColumn: { md: "span 2" } }}>
          <TextField size="small" fullWidth label={t("emp.col.email")} value={form.company_email} onChange={set("company_email")}
            error={emailCheck ? !emailCheck.free : false}
            helperText={emailCheck ? (emailCheck.free ? t("emp.card.email_free") : emailCheck.why) : t("emp.card.email_hint")} />
          <Stack direction="row" spacing={0.75} sx={{ mt: 0.5 }}><Chip size="small" label={providerChip} /></Stack>
        </Box>
      </Box>

      <Typography sx={{ fontWeight: 700, mt: 1.5, mb: 0.5, fontSize: 14 }}>{t("emp.card.roles")}</Typography>
      <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
        {ROLE_CHOICES.map((r) => (
          <Chip key={r} label={r} color={roles.includes(r) ? "primary" : "default"} variant={roles.includes(r) ? "filled" : "outlined"} disabled={r === "Employee"}
            onClick={() => setRoles((x) => (x.includes(r) ? x.filter((y) => y !== r) : [...x, r]))} />
        ))}
      </Stack>
      <Typography sx={{ fontSize: 13, color: f.muted, mt: 1 }}>
        {t("emp.card.will_invite", { email: form.company_email || p.personal_email || "", personal: p.personal_email ?? "" })}
        {p.has_bank_id ? ` ${t("emp.card.bank_id")}` : ""}
      </Typography>

      {(p.steps ?? []).length > 0 && (
        <Stack spacing={0.5} sx={{ mt: 1.5 }}>
          {(p.steps ?? []).map((s) => (
            <Typography key={s.step} sx={{ fontSize: 13, color: s.ok ? f.ok : f.coral }}>
              {s.ok ? "✓" : "✗"} {t(STEP_KEYS[s.step] ?? s.step)}{s.ok ? "" : ` - ${s.error}`}
            </Typography>
          ))}
        </Stack>
      )}
      {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}
      <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
        <Button variant="contained" onClick={approve} disabled={busy || (emailCheck ? !emailCheck.free : false) || (p.match?.kind === "possible" && !decision)}>
          {failed.length ? t("emp.card.retry") : t("emp.card.approve")}
        </Button>
        <Button onClick={later} disabled={busy}>{t("emp.card.later")}</Button>
      </Stack>
    </Card>
  );
}

export function ItTodoCard({ todo, onChanged }: { todo: ItTodo; onChanged: () => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [address, setAddress] = useState(todo.address);
  const [error, setError] = useState<string | null>(null);
  const done = async () => {
    setError(null);
    try { await employeesApi.itDone(todo.id, todo.kind === "it_mailbox_create" ? address : undefined); onChanged(); } catch (e) { setError(extractErrorMessage(e, "")); }
  };
  return (
    <Card data-testid="it-todo" sx={{ p: 1.5, border: `1px solid ${f.line}` }}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1} alignItems={{ md: "center" }}>
        <Emoji name="laptop" size={20} />
        <Typography sx={{ fontWeight: 700, flex: 1 }}>{todo.title}</Typography>
        {todo.kind === "it_mailbox_create" && <TextField size="small" label={t("emp.it.address")} value={address} onChange={(e) => setAddress(e.target.value)} sx={{ minWidth: 260 }} />}
        <Button variant="contained" onClick={done}>{todo.kind === "it_mailbox_create" ? t("emp.it.done_create") : t("emp.it.done_suspend")}</Button>
      </Stack>
      {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}
    </Card>
  );
}
