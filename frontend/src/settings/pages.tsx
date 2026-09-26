import { useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import MenuItem from "@mui/material/MenuItem";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { experienceApi, extractErrorMessage, http, reportsApi, type HealthIssue } from "../api/client";
import type { AuditLogRead } from "../api/types";
import MfaSettingsCard from "../components/MfaSettingsCard";
import PlatformSettingsPanel from "../components/PlatformSettingsPanel";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";
import { LOCALES, useT } from "../i18n";
import { en as baseEn } from "../i18n/en";
import { EmptyState, Emoji, InfoTip, StatTile, StatusChip } from "../ui-kit";

// Part 16.3: the Settings pages that didn't exist as panels before.

function Section({ title, emoji, intro, children }: { title: string; emoji: string; intro?: string; children: React.ReactNode }) {
  const f = useTheme().palette.fresh;
  return (
    <Card>
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
          <Emoji name={emoji} size={22} />
          <Typography variant="h6">{title}</Typography>
        </Stack>
        {intro && <Typography sx={{ color: f.muted, mb: 2 }}>{intro}</Typography>}
        {children}
      </CardContent>
    </Card>
  );
}

// ---- People & access > 2-step verification ----

export function TwoStepPage() {
  const t = useT();
  const { can } = useMeBootstrap();
  const admin = can("platform.settings.configure");
  const [issue, setIssue] = useState<HealthIssue | null>(null);
  const [sent, setSent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!admin) return;
    experienceApi.configHealth().then((r) => setIssue(r.issues.find((i) => i.code === "USERS_WITHOUT_2FA" || i.code === "ADMIN_WITHOUT_2FA") ?? null)).catch(() => undefined);
  }, [admin]);

  const invite = () => {
    http.post<{ people: number; reminded: number }>("/api/v1/settings/two-step/invite")
      .then((r) => setSent(r.reminded)).catch((err) => setError(extractErrorMessage(err, t("error.failed"))));
  };

  return (
    <Stack spacing={2.5}>
      <MfaSettingsCard />
      {admin && (
        <Section title={t("settingsHome.twostep.team_title")} emoji="people" intro={t("settingsHome.twostep.team_intro")}>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
          {sent !== null ? (
            <Alert severity="success">{t("settingsHome.twostep.sent", { count: sent })}</Alert>
          ) : issue ? (
            <Alert severity="warning" action={<Button variant="contained" size="small" onClick={invite}>{issue.action_label ?? t("settingsHome.twostep.invite")}</Button>}>
              {issue.message}
            </Alert>
          ) : (
            <Alert severity="success">{t("settingsHome.twostep.all_set")}</Alert>
          )}
          <Box sx={{ mt: 2 }}>
            <PlatformSettingsPanel prefixes={["iam.auth.mfa"]} title={t("settingsHome.twostep.rule_title")} intro={t("settingsHome.twostep.rule_intro")} />
          </Box>
        </Section>
      )}
    </Stack>
  );
}

// ---- Company > Languages (company renames of any label, per language) ----

interface OverrideRow { id: string; locale: string; key: string; value: string }

export function LanguagesPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { reload } = useMeBootstrap();
  const [locale, setLocale] = useState("en");
  const [rows, setRows] = useState<OverrideRow[] | null>(null);
  const [find, setFind] = useState("");
  const [pick, setPick] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setRows(null);
    http.get<OverrideRow[]>(`/api/v1/i18n/overrides?locale=${locale}`).then(setRows).catch((err) => {
      setRows([]);
      setError(extractErrorMessage(err, t("error.failed")));
    });
  };
  useEffect(load, [locale]); // eslint-disable-line react-hooks/exhaustive-deps

  // Find a label by what it SAYS (never by its key).
  const matches = useMemo(() => {
    const q = find.trim().toLowerCase();
    if (q.length < 2) return [];
    return Object.entries(baseEn as Record<string, string>).filter(([, text]) => text.toLowerCase().includes(q)).slice(0, 8);
  }, [find]);

  const save = () => {
    if (!pick || !value.trim()) return;
    http.put("/api/v1/i18n/overrides", { locale, key: pick, value: value.trim() })
      .then(() => { setPick(null); setValue(""); setFind(""); load(); reload(); })
      .catch((err) => setError(extractErrorMessage(err, t("error.failed"))));
  };
  const remove = (id: string) => http.del(`/api/v1/i18n/overrides/${id}`).then(() => { load(); reload(); }).catch(() => undefined);

  return (
    <Section title={t("settingsHome.lang.title")} emoji="globe" intro={t("settingsHome.lang.intro")}>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 2 }}>
        <TextField select label={t("settingsHome.lang.language")} value={locale} onChange={(e) => setLocale(e.target.value)} sx={{ minWidth: 180 }}>
          {LOCALES.map((l) => <MenuItem key={l.code} value={l.code}>{l.label}</MenuItem>)}
        </TextField>
        <TextField label={t("settingsHome.lang.find")} value={find} onChange={(e) => { setFind(e.target.value); setPick(null); }} fullWidth
          placeholder={t("settingsHome.lang.find_example")} helperText={t("settingsHome.lang.find_hint")} />
      </Stack>
      {matches.length > 0 && !pick && (
        <Stack spacing={0.75} sx={{ mb: 2 }}>
          {matches.map(([key, text]) => (
            <Button key={key} variant="outlined" onClick={() => { setPick(key); setValue(text); }} sx={{ justifyContent: "flex-start", textTransform: "none" }}>{text}</Button>
          ))}
        </Stack>
      )}
      {pick && (
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }} sx={{ mb: 2, p: 2, borderRadius: "12px", bgcolor: f.surface2 }}>
          <Typography sx={{ minWidth: 200 }}>«{(baseEn as Record<string, string>)[pick]}» →</Typography>
          <TextField label={t("settingsHome.lang.new_text")} value={value} onChange={(e) => setValue(e.target.value)} fullWidth placeholder={t("settingsHome.lang.new_example")} />
          <Button variant="contained" onClick={save}>{t("action.save")}</Button>
        </Stack>
      )}
      {rows === null ? <Skeleton variant="rounded" height={80} /> : rows.length === 0 ? (
        <EmptyState compact illustration="settings" title={t("settingsHome.lang.none")} />
      ) : (
        <Stack spacing={1}>
          {rows.map((r) => (
            <Stack key={r.id} direction="row" spacing={2} alignItems="center" sx={{ p: 1.25, borderRadius: "12px", border: `1px solid ${f.line}` }}>
              <Typography sx={{ flex: 1, color: f.muted }}>{(baseEn as Record<string, string>)[r.key] ?? r.key.replace(/[._]/g, " ")}</Typography>
              <Typography sx={{ flex: 1, fontWeight: 700 }}>{r.value}</Typography>
              <Button size="small" color="error" onClick={() => remove(r.id)}>{t("action.remove")}</Button>
            </Stack>
          ))}
        </Stack>
      )}
    </Section>
  );
}

// ---- Billing & licence ----

export function BillingPage() {
  const t = useT();
  const [data, setData] = useState<{ active_employees: number; users: number; modules: string[]; plan: string | null } | null | false>(null);
  useEffect(() => { http.get<typeof data>("/api/v1/settings/usage").then((d) => setData(d)).catch(() => setData(false)); }, []);
  if (data === null) return <Skeleton variant="rounded" height={160} />;
  if (data === false) return <Alert severity="error">{t("home.load_failed")}</Alert>;
  return (
    <Stack spacing={2.5}>
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(3, 1fr)" } }}>
        <StatTile emoji="people" label={t("settingsHome.billing.employees")} value={data.active_employees} tone="brand" />
        <StatTile emoji="id_card" label={t("settingsHome.billing.users")} value={data.users} tone="sky" />
        <StatTile emoji="puzzle" label={t("settingsHome.billing.modules")} value={data.modules.length} tone="sun" />
      </Box>
      <Section title={t("settingsHome.billing.plan")} emoji="money" intro={t("settingsHome.billing.plan_intro")}>
        <Typography sx={{ fontWeight: 700, mb: 1 }}>{data.plan ?? t("settingsHome.billing.no_plan")}</Typography>
        <Stack direction="row" flexWrap="wrap" gap={1}>
          {data.modules.map((m) => <StatusChip key={m} status="active" label={t(`nav.${m}`) === `nav.${m}` ? m.replace(/_/g, " ") : t(`nav.${m}`)} />)}
        </Stack>
      </Section>
    </Stack>
  );
}

// ---- Data & privacy > Imports & exports ----

export function ImportsPage({ go }: { go: (path: string) => void }) {
  const t = useT();
  const items = [
    { emoji: "technologist", title: t("settingsHome.imports.candidates"), to: "/candidates/import" },
    { emoji: "people", title: t("settingsHome.imports.employees"), to: "/employees?import=1" },
    { emoji: "bar_chart", title: t("settingsHome.imports.reports"), to: "/reports" },
  ];
  return (
    <Section title={t("settingsHome.imports.title")} emoji="package" intro={t("settingsHome.imports.intro")}>
      <Stack spacing={1}>
        {items.map((i) => (
          <Stack key={i.to} direction="row" spacing={1.5} alignItems="center">
            <Emoji name={i.emoji} size={20} />
            <Typography sx={{ flex: 1, fontWeight: 600 }}>{i.title}</Typography>
            <Button variant="outlined" size="small" component={RouterLink} to={i.to}>{t("home.alert.open")}</Button>
          </Stack>
        ))}
        <Button sx={{ alignSelf: "flex-start", mt: 1 }} onClick={() => go("data/samples")} startIcon={<Emoji name="page" size={16} />}>{t("settingsHome.imports.samples")}</Button>
      </Stack>
    </Section>
  );
}

// ---- Data & privacy > Sample files (filled in by 16.8) ----

interface SampleRow { key: string; name: string; description: string; format: string }

export function SamplesPage() {
  const t = useT();
  const [rows, setRows] = useState<SampleRow[] | null>(null);
  useEffect(() => { http.get<SampleRow[]>("/api/v1/samples").then(setRows).catch(() => setRows([])); }, []);
  const download = async (key: string, name: string, format: string) => {
    const blob = await http.fetchBlob(`/api/v1/samples/${key}`);
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name}.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Section title={t("settingsHome.samples.title")} emoji="page" intro={t("settingsHome.samples.intro")}>
      {rows === null ? <Skeleton variant="rounded" height={120} /> : rows.length === 0 ? (
        <EmptyState compact illustration="files-uploading" title={t("settingsHome.samples.none")} />
      ) : (
        <Stack spacing={1}>
          {rows.map((r) => (
            <Stack key={r.key} direction="row" spacing={1.5} alignItems="center" sx={{ py: 0.75 }}>
              <Emoji name="page" size={20} />
              <Box sx={{ flex: 1 }}>
                <Typography sx={{ fontWeight: 700 }}>{r.name}</Typography>
                <Typography variant="caption">{r.description}</Typography>
              </Box>
              <Button size="small" variant="outlined" onClick={() => download(r.key, r.name, r.format)}>{t("settingsHome.samples.download", { format: r.format.toUpperCase() })}</Button>
            </Stack>
          ))}
        </Stack>
      )}
    </Section>
  );
}

// ---- Integrations > File storage (filled in by 16.4) ----

export function StoragePage() {
  const t = useT();
  const [data, setData] = useState<{ provider: string; location: string; used_bytes: number; files: number; by_kind: { kind: string; files: number; bytes: number }[] } | null | false>(null);
  useEffect(() => { http.get<typeof data>("/api/v1/settings/storage").then((d) => setData(d)).catch(() => setData(false)); }, []);
  const mb = (b: number) => (b / (1024 * 1024)).toFixed(1);
  return (
    <Section title={t("settingsHome.storage.title")} emoji="file_folder" intro={t("settingsHome.storage.intro")}>
      {data === null ? <Skeleton variant="rounded" height={100} /> : data === false ? (
        <Alert severity="info">{t("settingsHome.storage.unavailable")}</Alert>
      ) : (
        <Stack spacing={2}>
          <Typography>
            <b>{t("settingsHome.storage.where")}</b> {data.location} <InfoTip text={t("settingsHome.storage.where_info")} />
          </Typography>
          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(2, 1fr)" } }}>
            <StatTile emoji="file_folder" label={t("settingsHome.storage.files")} value={data.files} tone="sky" />
            <StatTile emoji="package" label={t("settingsHome.storage.used")} value={`${mb(data.used_bytes)} MB`} tone="brand" />
          </Box>
          <Stack spacing={0.5}>
            {data.by_kind.map((k) => (
              <Typography key={k.kind} sx={{ fontSize: 14 }}>{t(`settingsHome.storage.kind.${k.kind}`)}: {k.files} · {mb(k.bytes)} MB</Typography>
            ))}
          </Stack>
        </Stack>
      )}
    </Section>
  );
}

// ---- Data & privacy > Audit log ----

export function AuditLogPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [rows, setRows] = useState<AuditLogRead[] | null>(null);
  useEffect(() => { reportsApi.auditLog({ limit: 100 }).then((p) => setRows(p.items)).catch(() => setRows([])); }, []);
  const words = (s?: string | null) => (s ?? "").replace(/[._]/g, " ");
  return (
    <Section title={t("settingsHome.audit.title")} emoji="eyes" intro={t("settingsHome.audit.intro")}>
      {rows === null ? <Skeleton variant="rounded" height={160} /> : rows.length === 0 ? (
        <EmptyState compact illustration="no-data" title={t("settingsHome.audit.none")} />
      ) : (
        <Stack spacing={0.75}>
          {rows.map((r) => (
            <Stack key={r.id} direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ py: 0.75, borderBottom: `1px solid ${f.line}` }}>
              <Typography sx={{ minWidth: 170, color: f.muted, fontSize: 13 }}>{new Date(r.created_at).toLocaleString()}</Typography>
              <Typography sx={{ minWidth: 180, fontWeight: 600, fontSize: 14 }}>{r.actor ?? t("settingsHome.audit.system")}</Typography>
              <Typography sx={{ fontSize: 14 }}>{words(r.action)} · {words(r.entity_type)}</Typography>
            </Stack>
          ))}
        </Stack>
      )}
    </Section>
  );
}
