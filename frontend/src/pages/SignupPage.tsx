import { useEffect, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import LinearProgress from "@mui/material/LinearProgress";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { ApiError, http } from "../api/client";
import PublicAuthLayout from "../components/careers/PublicAuthLayout";
import { useT } from "../i18n";

// Part 28.5: "Create your company" on the platform domain. The rules are the installer's (backend validate.py);
// the server answers with every problem at once. After the emailed link (30 min, single use) the company is
// created in the background; the modules wait for CTD Techs' approval, then a "ready" email follows.
type Problems = Record<string, string>;
interface Status { status: string; company: string; host: string; admin_email: string; error: string | null; sign_in_url: string | null }
const API = "/api/v1/platform/signup";

function SignupForm() {
  const t = useT();
  const [f, setF] = useState({ company_name: "", company_slug: "", admin_name: "", admin_email: "", password: "", password2: "", captcha_answer: "" });
  const [touchedSlug, setTouchedSlug] = useState(false);
  const [modules, setModules] = useState<{ key: string; name: string }[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [captcha, setCaptcha] = useState<{ question: string; token: string } | null>(null);
  const [problems, setProblems] = useState<Problems>({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const newCaptcha = () => http.get<{ question: string; token: string }>(`${API}/captcha`).then(setCaptcha).catch(() => setCaptcha(null));
  useEffect(() => {
    void newCaptcha();
    http.get<{ key: string; name: string }[]>(`${API}/modules`).then(setModules).catch(() => setModules([]));
  }, []);
  const set = (k: keyof typeof f, v: string) => {
    setF((x) => ({ ...x, [k]: v, ...(k === "company_name" && !touchedSlug ? { company_slug: v.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) } : {}) }));
  };
  const submit = async () => {
    setBusy(true); setError(null); setProblems({});
    if (f.password !== f.password2) { setProblems({ password: t("signup.pw_mismatch") }); setBusy(false); return; }
    try {
      const r = await http.post<{ message: string }>(API, { ...f, modules: Array.from(chosen), captcha_token: captcha?.token ?? "" });
      setDone(r.message);
    } catch (e) {
      const detail = e instanceof ApiError ? (e.detail as { problems?: Problems } | string) : null;
      if (detail && typeof detail === "object" && detail.problems) setProblems(detail.problems);
      else setError(typeof detail === "string" ? detail : t("signup.failed"));
      void newCaptcha();
    } finally { setBusy(false); }
  };
  if (done) return <Alert severity="success" role="status">{done}</Alert>;
  const field = (k: keyof typeof f, label: string, type = "text", extra: object = {}) => (
    <TextField label={label} type={type} value={f[k]} onChange={(e) => set(k, e.target.value)} error={!!problems[k === "password2" ? "password" : k]}
      helperText={k === "password2" ? undefined : problems[k]} fullWidth {...extra} />
  );
  return (
    <Stack spacing={2} component="form" noValidate onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      {error && <Alert severity="error">{error}</Alert>}
      {field("company_name", t("signup.company"))}
      <TextField label={t("signup.slug")} value={f.company_slug} onChange={(e) => { setTouchedSlug(true); set("company_slug", e.target.value); }}
        error={!!problems.company_slug} helperText={problems.company_slug ?? t("signup.slug_hint", { host: `${f.company_slug || "your-company"}.…` })} fullWidth />
      {field("admin_name", t("signup.name"))}
      {field("admin_email", t("signup.email"), "email")}
      {field("password", t("signup.password"), "password", { autoComplete: "new-password" })}
      {field("password2", t("signup.password2"), "password", { autoComplete: "new-password" })}
      <Typography variant="caption" sx={{ color: "text.secondary", mt: -1 }}>{t("signup.pw_rules")}</Typography>
      {modules.length > 0 && (
        <Box>
          <Typography sx={{ fontWeight: 700 }}>{t("signup.modules")}</Typography>
          <Typography variant="caption" sx={{ color: "text.secondary" }}>{t("signup.modules_hint")}</Typography>
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" } }}>
            {modules.map((m) => (
              <FormControlLabel key={m.key} label={m.name} control={<Checkbox checked={chosen.has(m.key)}
                onChange={() => setChosen((s) => { const n = new Set(s); if (n.has(m.key)) n.delete(m.key); else n.add(m.key); return n; })} />} />
            ))}
          </Box>
          {problems.modules && <Typography variant="caption" color="error">{problems.modules}</Typography>}
        </Box>
      )}
      <TextField label={captcha?.question ?? t("signup.captcha_loading")} value={f.captcha_answer} onChange={(e) => set("captcha_answer", e.target.value)}
        error={!!problems.captcha} helperText={problems.captcha ?? t("signup.captcha_hint")} inputMode="numeric" />
      <Button type="submit" variant="contained" size="large" disabled={busy}>{t("signup.submit")}</Button>
      <Typography variant="body2" textAlign="center"><Link component={RouterLink} to="/login">{t("signup.have_account")}</Link></Typography>
    </Stack>
  );
}

function ConfirmAndProgress({ token }: { token: string }) {
  const t = useT();
  const [s, setS] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let stop = false;
    const poll = () => http.get<Status>(`${API}/status?token=${encodeURIComponent(token)}`).then((r) => {
      if (stop) return;
      setS(r);
      if (["confirmed", "provisioning"].includes(r.status)) window.setTimeout(poll, 2000);
    }).catch((e) => setError(e instanceof ApiError && typeof e.detail === "string" ? e.detail : t("signup.failed")));
    http.post<Status>(`${API}/confirm`, { token }).then((r) => { setS(r); poll(); })
      .catch((e) => setError(e instanceof ApiError && typeof e.detail === "string" ? e.detail : t("signup.failed")));
    return () => { stop = true; };
  }, [token, t]);
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!s) return <LinearProgress aria-label={t("signup.creating")} />;
  if (s.status === "failed") return <Alert severity="error">{t("signup.st.failed")} {s.error}</Alert>;
  return (
    <Stack spacing={2} role="status">
      <Typography sx={{ fontWeight: 700 }}>{s.company} · {s.host}</Typography>
      {["confirmed", "provisioning"].includes(s.status) && <><LinearProgress /><Typography>{t("signup.st.creating")}</Typography></>}
      {s.status === "waiting_approval" && <Alert severity="info">{t("signup.st.waiting", { email: s.admin_email })}</Alert>}
      {s.status === "active" && <Alert severity="success">{t("signup.st.active")}</Alert>}
      {s.sign_in_url && ["waiting_approval", "active"].includes(s.status) && <Button variant="contained" href={s.sign_in_url}>{t("signup.sign_in")}</Button>}
    </Stack>
  );
}

export default function SignupPage() {
  const t = useT();
  const [params] = useSearchParams();
  const token = params.get("token");
  return (
    <PublicAuthLayout illustration="secure-login" headline={t("signup.headline")} tagline={t("signup.tagline")}>
      <Typography variant="h1" component="h1" sx={{ fontSize: 26, mb: 2 }}>{token ? t("signup.confirm_title") : t("signup.title")}</Typography>
      {token ? <ConfirmAndProgress token={token} /> : <SignupForm />}
    </PublicAuthLayout>
  );
}
