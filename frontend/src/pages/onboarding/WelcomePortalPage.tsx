import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Checkbox from "@mui/material/Checkbox";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";
import { useParams, useSearchParams } from "react-router-dom";

import { ApiError, mediaApi } from "../../api/client";
import { welcomePortalApi, type PortalField, type PortalStep, type PortalSummary } from "../../api/onboardingExtra";
import { useBootstrap } from "../../bootstrap/BootstrapContext";
import { BrandMark, LanguagePicker } from "../../components/careers/PublicAuthLayout";
import DocumentCapture from "../../components/onboarding/DocumentCapture";
import { useDateText } from "../../components/onboarding/shared";
import { useI18n } from "../../i18n";
import { Emoji, FriendlyError, Illustration, UserAvatar, useReducedMotion } from "../../ui-kit";

// Part 15.6 (L-P1, P2): the pre-joiner portal -- public, no staff login, no app shell. The
// joiner is identified only by the link HR sends (/welcome?token=... or /welcome/<token>).
// Laid out like the NEW JOINER section of docs/ui/reference_mockup.html: welcome card with
// the company's video, progress bar, big step cards, first-day agenda, buddy card.

function stepEmoji(step: PortalStep): string {
  const c = step.code.toLowerCase();
  if (step.kind === "offer") return "writing_hand";
  if (step.kind === "policy") return "clipboard";
  if (/bank|cheque|salary/.test(c)) return "bank";
  if (/photo|selfie|picture/.test(c)) return "camera";
  if (/edu|degree|mark|certificate|school|college/.test(c)) return "graduation";
  if (/pan|aadhaar|aadhar|passport|id|identity|voter|licen/.test(c)) return "id_card";
  if (/address/.test(c)) return "house";
  if (/emergency|family|contact/.test(c)) return "people";
  return step.kind === "form" ? "memo" : "page";
}

function exampleFor(field: PortalField): string {
  if (field.placeholder) return field.placeholder;
  const k = field.key.toLowerCase();
  if (/pan/.test(k)) return "ABCDE1234F";
  if (/ifsc/.test(k)) return "HDFC0001234";
  if (/account/.test(k)) return "123456789012";
  if (/phone|mobile/.test(k)) return "+91 98765 43210";
  if (/email/.test(k) || field.format === "email") return "ananya.rao@gmail.com";
  if (/pin|postal|zip/.test(k)) return "600040";
  if (/aadhaar|aadhar/.test(k)) return "1234 5678 9012";
  if (/city/.test(k)) return "Chennai";
  if (/name/.test(k)) return "Ananya Rao";
  return "";
}

export default function WelcomePortalPage() {
  const f = useTheme().palette.fresh;
  const { t, locale } = useI18n();
  const d = useDateText();
  const reduced = useReducedMotion();
  const phone = useMediaQuery(useTheme().breakpoints.down("sm"));
  const { branding } = useBootstrap();
  const params = useParams<{ token?: string }>();
  const [search] = useSearchParams();
  const token = params.token || search.get("token") || "";

  const [data, setData] = useState<PortalSummary | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [open, setOpen] = useState<PortalStep | null>(null);
  const [barWidth, setBarWidth] = useState(0);
  const [videoBroken, setVideoBroken] = useState(false);

  const load = useCallback(() => {
    if (!token) return;
    setError(null);
    welcomePortalApi.summary(token, locale).then(setData).catch(setError);
  }, [token, locale]);

  useEffect(load, [load]);

  const percent = data && data.total ? Math.round((100 * data.done) / data.total) : data ? 100 : 0;
  useEffect(() => {
    if (!data) return;
    if (reduced) {
      setBarWidth(percent);
      return;
    }
    const id = window.setTimeout(() => setBarWidth(percent), 80);
    return () => window.clearTimeout(id);
  }, [data, percent, reduced]);

  const linkBroken = !token || (error instanceof ApiError && (error.status === 401 || error.status === 404));
  const minutesLeft = data ? Math.max(0, data.total - data.done) * 2 : 0;
  const media = data?.welcome_media;
  const isVideo = Boolean(media && media.content_type.startsWith("video/"));

  const shell = (children: ReactNode) => (
    <Box sx={{ minHeight: "100vh", bgcolor: f.ground, display: "flex", flexDirection: "column" }}>
      <Box component="header" sx={{ bgcolor: f.surface, boxShadow: f.shadow }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={2} sx={{ maxWidth: 1080, mx: "auto", px: 2, py: 1.5 }}>
          <BrandMark size={34} />
          <LanguagePicker />
        </Stack>
      </Box>
      <Box component="main" sx={{ width: "100%", maxWidth: 1080, mx: "auto", px: 2, py: { xs: 2.5, md: 4 }, flex: 1 }}>{children}</Box>
      <Box component="footer" sx={{ py: 2.5, textAlign: "center", color: f.muted, fontSize: 13 }}>
        {branding?.support_contact ? t("welcome.footer_help", { contact: branding.support_contact }) : t("welcome.footer_plain")}
      </Box>
    </Box>
  );

  if (linkBroken) {
    return shell(
      <Card sx={{ p: { xs: 2.5, md: 4 }, textAlign: "center" }}>
        <Illustration name="access-denied" height={150} />
        <Typography component="h1" sx={{ fontWeight: 800, fontSize: 22, mt: 2 }}>{t("welcome.link_broken")}</Typography>
        <Typography sx={{ color: f.muted, mt: 1, maxWidth: "52ch", mx: "auto" }}>{t("welcome.link_broken_fix")}</Typography>
        {branding?.support_contact && (
          <Button variant="contained" sx={{ mt: 2 }} href={`mailto:${branding.support_contact}`}>{t("welcome.email_hr")}</Button>
        )}
      </Card>,
    );
  }

  if (error) {
    return shell(<FriendlyError what={t("welcome.load_failed")} fix={t("welcome.load_failed_fix")} onRetry={load} />);
  }

  if (!data) {
    return shell(
      <Box sx={{ display: "grid", placeItems: "center", py: 10 }} role="status">
        <CircularProgress aria-label={t("welcome.loading")} />
      </Box>,
    );
  }

  const allDone = data.total > 0 && data.done >= data.total;
  const cardSx = { p: { xs: 2, md: 2.5 } };

  return shell(
    <Stack spacing={2.25}>
      {/* welcome card */}
      <Card
        sx={{
          ...cardSx, display: "grid", gap: 2.5, alignItems: "center",
          gridTemplateColumns: { xs: "1fr", md: "1.2fr 1fr" },
          background: `linear-gradient(135deg, ${f.sunSoft}, ${f.surface} 55%, ${f.brandSoft})`,
        }}
      >
        <Box>
          <Box aria-hidden sx={{ fontSize: 44, lineHeight: 1 }}><Emoji name={allDone ? "tada_face" : "party"} size={44} /></Box>
          <Typography component="h1" sx={{ fontWeight: 800, fontSize: { xs: 24, md: 28 }, lineHeight: 1.2, mt: 1, textWrap: "balance" }}>
            {t("welcome.hello", { name: data.first_name })}
          </Typography>
          <Typography sx={{ color: f.muted, fontSize: 15, mt: 1, mb: 1.75 }}>
            {data.days_to_join >= 0
              ? <>{t("welcome.join_on")} <b style={{ color: f.ink }}>{d.long(data.joining_date)}</b>{data.role ? ` · ${data.role}` : ""}. {allDone ? t("welcome.all_set") : t("welcome.finish_steps")}</>
              : t("welcome.joined_already")}
          </Typography>
          <Box
            role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label={t("welcome.progress_aria", { percent })}
            sx={{ height: 10, borderRadius: 5, bgcolor: f.line, overflow: "hidden" }}
          >
            <Box sx={{ height: "100%", width: `${barWidth}%`, background: `linear-gradient(90deg, ${f.brand}, ${f.sun})`, transition: reduced ? "none" : "width 1.2s ease" }} />
          </Box>
          <Typography sx={{ color: f.muted, fontSize: 13, mt: 0.75 }}>
            <b style={{ color: f.ink }}>{t("welcome.done_of", { done: data.done, total: data.total })}</b>
            {!allDone && minutesLeft > 0 ? ` · ${t("welcome.minutes_left", { count: minutesLeft })}` : ""}
          </Typography>
        </Box>
        <Box>
          {media && !videoBroken ? (
            isVideo ? (
              <Box
                component="video" controls playsInline preload="metadata" src={mediaApi.fileUrl("welcome.video")}
                aria-label={media.title || t("welcome.video_label")} onError={() => setVideoBroken(true)}
                sx={{ width: "100%", aspectRatio: "16 / 10", borderRadius: "16px", bgcolor: "#000", display: "block", objectFit: "cover" }}
              />
            ) : (
              <Box
                component="img" src={mediaApi.fileUrl("welcome.video")} alt={media.title || t("welcome.video_label")} onError={() => setVideoBroken(true)}
                sx={{ width: "100%", aspectRatio: "16 / 10", borderRadius: "16px", objectFit: "cover", display: "block" }}
              />
            )
          ) : (
            <Illustration name="welcome-aboard" height={phone ? 150 : 200} sx={{ mx: "auto" }} />
          )}
          {media && !videoBroken && (
            <Typography sx={{ fontSize: 12, color: f.muted, mt: 0.75, textAlign: "center" }}>{media.title || t("welcome.video_caption")}</Typography>
          )}
        </Box>
      </Card>

      {data.welcome.message && (
        <Card sx={{ ...cardSx, borderLeft: `4px solid ${f.brand}` }}>
          <Typography sx={{ fontWeight: 700, mb: 0.5 }}><Emoji name="speech" /> {t("welcome.note_from_hr")}</Typography>
          <Typography sx={{ whiteSpace: "pre-line", maxWidth: "70ch" }}>{data.welcome.message}</Typography>
        </Card>
      )}

      {/* steps */}
      <Card sx={cardSx}>
        <Typography component="h2" sx={{ fontWeight: 700, fontSize: 16, mb: 1.5, display: "flex", justifyContent: "space-between", gap: 1, flexWrap: "wrap" }}>
          {t("welcome.steps_title")}
          <Typography component="span" sx={{ color: f.muted, fontSize: 12, fontWeight: 500 }}>{t("welcome.steps_hint")}</Typography>
        </Typography>
        {data.steps.length === 0 ? (
          <Typography sx={{ color: f.muted }}>{t("welcome.no_steps")}</Typography>
        ) : (
          <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", md: "repeat(3, minmax(0, 1fr))" } }}>
            {data.steps.map((step) => (
              <StepCard key={`${step.kind}:${step.code}`} step={step} onOpen={() => setOpen(step)} />
            ))}
            {branding?.support_contact && (
              <Box
                component="a" href={`mailto:${branding.support_contact}`}
                sx={{ textDecoration: "none", color: "inherit", border: `1px solid ${f.line}`, borderRadius: "16px", p: 1.75, display: "flex", flexDirection: "column", gap: 0.75, bgcolor: f.surface2, "&:focus-visible": { outline: `2px solid ${f.brand}`, outlineOffset: 2 } }}
              >
                <Emoji name="question" size={28} />
                <Typography sx={{ fontWeight: 700 }}>{t("welcome.questions")}</Typography>
                <Typography sx={{ fontSize: 13, color: f.muted }}>{t("welcome.questions_hint")}</Typography>
              </Box>
            )}
          </Box>
        )}
      </Card>

      {(data.welcome.agenda.length > 0 || data.welcome.buddy) && (
        <Box sx={{ display: "grid", gap: 2.25, gridTemplateColumns: { xs: "1fr", md: data.welcome.agenda.length && data.welcome.buddy ? "1.4fr 1fr" : "1fr" } }}>
          {data.welcome.agenda.length > 0 && (
            <Card sx={cardSx}>
              <Typography component="h2" sx={{ fontWeight: 700, fontSize: 16, mb: 1.5 }}>{t("welcome.first_day")}</Typography>
              <Stack component="ul" spacing={1} sx={{ listStyle: "none", p: 0, m: 0 }}>
                {data.welcome.agenda.map((item, i) => (
                  <Stack component="li" key={i} direction="row" spacing={1.25} alignItems="center" sx={{ p: 1, borderRadius: "10px", bgcolor: f.surface2 }}>
                    {item.time && <Box component="time" sx={{ fontWeight: 700, minWidth: 62, fontVariantNumeric: "tabular-nums" }}>{item.time}</Box>}
                    {item.emoji && <Emoji name={item.emoji} />}
                    <Typography>{item.title}</Typography>
                  </Stack>
                ))}
              </Stack>
            </Card>
          )}
          {data.welcome.buddy && (
            <Card sx={cardSx}>
              <Typography component="h2" sx={{ fontWeight: 700, fontSize: 16, mb: 1.5 }}>{t("welcome.buddy")}</Typography>
              <Stack direction="row" spacing={1.5} alignItems="center">
                <UserAvatar name={data.welcome.buddy.name} size={64} />
                <Box>
                  <Typography sx={{ fontWeight: 700 }}>{data.welcome.buddy.name}</Typography>
                  {data.welcome.buddy.title && <Typography sx={{ fontSize: 13, color: f.muted }}>{data.welcome.buddy.title}</Typography>}
                  {data.welcome.buddy.note && <Typography sx={{ fontSize: 13, color: f.muted }}>“{data.welcome.buddy.note}”</Typography>}
                </Box>
              </Stack>
              {data.welcome.buddy.email && (
                <Button variant="outlined" sx={{ mt: 1.75 }} href={`mailto:${data.welcome.buddy.email}`}><Emoji name="speech" />&nbsp;{t("welcome.say_hi")}</Button>
              )}
            </Card>
          )}
        </Box>
      )}

      <StepDialog step={open} token={token} fullScreen={phone} onClose={() => setOpen(null)} onDone={() => { setOpen(null); load(); }} />
    </Stack>,
  );
}

function StepCard({ step, onOpen }: { step: PortalStep; onOpen: () => void }) {
  const f = useTheme().palette.fresh;
  const { t } = useI18n();
  const label = step.kind === "offer" ? t("welcome.step.offer") : step.label;
  let note: string;
  let tone: "done" | "todo" | "warn" = step.done ? "done" : "todo";
  if (step.kind === "document") {
    if (step.status === "verified") note = t("welcome.step.doc_verified");
    else if (step.status === "pending") note = t("welcome.step.doc_uploaded");
    else if (step.status === "rejected") { note = t("welcome.step.doc_again"); tone = "warn"; }
    else note = t("welcome.step.doc_todo");
  } else if (step.kind === "form") note = step.done ? t("welcome.step.form_done") : t("welcome.step.form_todo", { count: step.fields.length });
  else if (step.kind === "policy") note = step.done ? t("welcome.step.policy_done") : t("welcome.step.policy_todo");
  else note = step.done ? t("welcome.step.offer_done") : t("welcome.step.offer_todo");

  const clickable = step.kind !== "offer" && !(step.kind === "document" && step.status === "verified") && !(step.kind === "policy" && step.done);
  return (
    <Box
      component={clickable ? "button" : "div"} type={clickable ? "button" : undefined} onClick={clickable ? onOpen : undefined}
      aria-label={`${label}: ${note}`}
      sx={{
        textAlign: "left", font: "inherit", color: "inherit", cursor: clickable ? "pointer" : "default", width: "100%",
        border: `1px solid ${tone === "done" ? "transparent" : tone === "warn" ? f.coral : f.line}`, borderRadius: "16px", p: 1.75,
        display: "flex", flexDirection: "column", gap: 0.75, minHeight: 112,
        bgcolor: tone === "done" ? f.okSoft : tone === "warn" ? f.coralSoft : f.surface2,
        "&:hover": clickable ? { boxShadow: f.shadow } : undefined,
        "&:focus-visible": { outline: `2px solid ${f.brand}`, outlineOffset: 2 },
      }}
    >
      <Emoji name={stepEmoji(step)} size={28} />
      <Typography component="span" sx={{ fontWeight: 700 }}>{label}</Typography>
      <Typography component="span" sx={{ fontSize: 13, color: tone === "warn" ? f.coral : f.muted, fontWeight: tone === "warn" ? 700 : 400 }}>
        {note}{step.done ? " ✓" : ""}
      </Typography>
    </Box>
  );
}

function StepDialog({ step, token, fullScreen, onClose, onDone }: { step: PortalStep | null; token: string; fullScreen: boolean; onClose: () => void; onDone: () => void }) {
  const f = useTheme().palette.fresh;
  const { t } = useI18n();
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    setProblem(null);
    setValues(step?.kind === "form" ? { ...step.saved } : {});
  }, [step]);

  const missing = useMemo(
    () => (step?.kind === "form" ? step.fields.filter((fl) => fl.required && (values[fl.key] === undefined || values[fl.key] === "")) : []),
    [step, values],
  );

  if (!step) return null;
  const title = step.kind === "offer" ? t("welcome.step.offer") : step.label;

  const explain = (e: unknown) =>
    e instanceof ApiError && e.status === 401 ? t("welcome.link_broken_fix")
      : e instanceof ApiError && typeof e.detail === "string" && e.status === 400 ? t("welcome.save_check")
        : t("welcome.save_failed");

  const submitForm = async () => {
    if (step.kind !== "form") return;
    if (missing.length) {
      setProblem(t("welcome.form.missing", { fields: missing.map((m) => m.label).join(", ") }));
      return;
    }
    setSaving(true);
    setProblem(null);
    try {
      await welcomePortalApi.submitForm(token, step.code, values);
      onDone();
    } catch (e) {
      setProblem(explain(e));
    } finally {
      setSaving(false);
    }
  };

  const acknowledge = async () => {
    setSaving(true);
    setProblem(null);
    try {
      await welcomePortalApi.acknowledgePolicy(token, step.code);
      onDone();
    } catch (e) {
      setProblem(explain(e));
    } finally {
      setSaving(false);
    }
  };

  const field = (fl: PortalField) => {
    const value = values[fl.key];
    const set = (v: unknown) => setValues((prev) => ({ ...prev, [fl.key]: v }));
    const hint = fl.hint ?? (fl.required ? t("welcome.form.required") : t("welcome.form.optional"));
    if (fl.type === "boolean") {
      return <FormControlLabel key={fl.key} control={<Checkbox checked={Boolean(value)} onChange={(e) => set(e.target.checked)} />} label={fl.label} />;
    }
    if (fl.options) {
      return (
        <TextField key={fl.key} select fullWidth label={fl.label} required={fl.required} value={value ?? ""} onChange={(e) => set(e.target.value)} helperText={hint}>
          {fl.options.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
        </TextField>
      );
    }
    const numeric = fl.type === "number" || fl.type === "integer";
    const type = fl.format === "date" ? "date" : fl.format === "email" ? "email" : numeric ? "number" : "text";
    return (
      <TextField
        key={fl.key} fullWidth label={fl.label} required={fl.required} type={type} placeholder={exampleFor(fl)} helperText={hint}
        value={value ?? ""} onChange={(e) => set(numeric ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value)}
        slotProps={type === "date" ? { inputLabel: { shrink: true } } : undefined}
      />
    );
  };

  return (
    <Dialog open onClose={onClose} fullScreen={fullScreen} fullWidth maxWidth="sm">
      <DialogTitle sx={{ display: "flex", alignItems: "center", gap: 1 }}><Emoji name={stepEmoji(step)} size={24} /> {title}</DialogTitle>
      <DialogContent>
        {step.kind === "document" && (
          <Stack spacing={1.5}>
            {step.status === "rejected" && step.rejection_reason && (
              <Alert severity="warning">{t("welcome.doc.hr_said", { reason: step.rejection_reason })}</Alert>
            )}
            {step.status === "pending" && <Alert severity="info">{t("welcome.doc.already")}</Alert>}
            <Typography sx={{ color: f.muted }}>{t("welcome.doc.intro", { label: step.label })}</Typography>
            <DocumentCapture
              label={step.label}
              onUpload={async (blob, filename) => {
                await welcomePortalApi.uploadDocument(token, step.code, blob, filename);
                onDone();
              }}
            />
          </Stack>
        )}
        {step.kind === "form" && (
          <Stack spacing={2} sx={{ pt: 1 }}>
            {step.done && <Alert severity="success">{t("welcome.form.saved_before")}</Alert>}
            {step.fields.length === 0 ? <Typography sx={{ color: f.muted }}>{t("welcome.form.no_fields")}</Typography> : step.fields.map(field)}
          </Stack>
        )}
        {step.kind === "policy" && (
          <Typography>{t("welcome.policy.body", { label: step.label })}</Typography>
        )}
        {problem && <Alert severity="warning" sx={{ mt: 2 }}>{problem}</Alert>}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} size="large">{t("action.close")}</Button>
        {step.kind === "form" && step.fields.length > 0 && (
          <Button variant="contained" size="large" onClick={submitForm} disabled={saving}>{saving ? t("welcome.saving") : t("welcome.form.save")}</Button>
        )}
        {step.kind === "policy" && (
          <Button variant="contained" size="large" onClick={acknowledge} disabled={saving}>{t("welcome.policy.agree")}</Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
