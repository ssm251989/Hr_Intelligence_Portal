import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { ApiError } from "../../api/client";
import { welcomePortalApi, type JoiningDoc, type JoiningField, type PortalContact, type PortalStep, type StepState } from "../../api/onboardingExtra";
import { useI18n } from "../../i18n";
import { Emoji, UserAvatar } from "../../ui-kit";
import DocumentCapture from "./DocumentCapture";
import { useDateText } from "./shared";

// Fix 2026-10-04 (offer -> welcome): the built-in welcome steps -- sign the offer, joining
// details (autosaved), joining documents (phone camera), day-one info -- and the contacts card.

type Builtin = Extract<PortalStep, { kind: "offer" | "joining_details" | "joining_documents" | "day_one" }>;

export function isBuiltin(step: PortalStep): step is Builtin {
  return step.kind === "offer" || step.kind === "joining_details" || step.kind === "joining_documents" || step.kind === "day_one";
}

export type CardTone = "done" | "todo" | "warn" | "locked" | "progress";
export interface CardView { label: string; description: string; note: string; tone: CardTone; emoji: string }

// fix 2026-10-05: every card shows its OWN state (never the offer's); literal keys for the i18n check
const STATE_KEY: Record<StepState, { labelKey: string }> = {
  locked: { labelKey: "wsteps.locked" }, not_started: { labelKey: "wsteps.state.not_started" },
  in_progress: { labelKey: "wsteps.state.in_progress" }, done: { labelKey: "wsteps.state.done" },
};
const TEXT_KEYS: Record<Builtin["kind"], { titleKey: string; hintKey: string; emoji: string }> = {
  offer: { titleKey: "wsteps.offer.sign_title", hintKey: "wsteps.offer.desc", emoji: "writing_hand" },
  joining_details: { titleKey: "wsteps.details.title", hintKey: "wsteps.details.desc", emoji: "memo" },
  joining_documents: { titleKey: "wsteps.docs.title", hintKey: "wsteps.docs.desc", emoji: "page" },
  day_one: { titleKey: "wsteps.day1.title", hintKey: "wsteps.day1.desc", emoji: "calendar" },
};

export function useStateText() {
  const { t } = useI18n();
  return (state: StepState) => t(STATE_KEY[state].labelKey);
}

export function useBuiltinCard() {
  const { t } = useI18n();
  const stateText = useStateText();
  return (step: Builtin): CardView => {
    const k = TEXT_KEYS[step.kind];
    const tone: CardTone = step.state === "locked" ? "locked" : step.state === "done" ? "done" : step.state === "in_progress" ? "progress" : "todo";
    let note = stateText(step.state);
    if (step.kind === "joining_documents" && step.state !== "locked" && step.documents.length) {
      const have = step.documents.filter((x) => x.status !== "missing" && x.status !== "rejected").length;
      if (step.documents.some((x) => x.status === "rejected")) return { label: t(k.titleKey), description: t(k.hintKey), note: t("welcome.step.doc_again"), tone: "warn", emoji: k.emoji };
      if (step.state !== "done") note = `${note} · ${t("wsteps.docs.count", { done: have, total: step.documents.length })}`;
    }
    return { label: t(k.titleKey), description: t(k.hintKey), note, tone, emoji: k.emoji };
  };
}

// literal keys so the i18n check can see them
const FIELD_KEYS: Record<string, { labelKey: string }> = {
  first_name: { labelKey: "wsteps.f.first_name" }, last_name: { labelKey: "wsteps.f.last_name" }, preferred_name: { labelKey: "wsteps.f.preferred_name" },
  date_of_birth: { labelKey: "wsteps.f.date_of_birth" }, phone: { labelKey: "wsteps.f.phone" }, personal_email: { labelKey: "wsteps.f.personal_email" },
  address_line1: { labelKey: "wsteps.f.address_line1" }, address_line2: { labelKey: "wsteps.f.address_line2" }, city: { labelKey: "wsteps.f.city" },
  state: { labelKey: "wsteps.f.state" }, pin_code: { labelKey: "wsteps.f.pin_code" }, emergency_name: { labelKey: "wsteps.f.emergency_name" },
  emergency_relation: { labelKey: "wsteps.f.emergency_relation" }, emergency_phone: { labelKey: "wsteps.f.emergency_phone" },
  bank_account_holder: { labelKey: "wsteps.f.bank_account_holder" }, bank_account_number: { labelKey: "wsteps.f.bank_account_number" },
  bank_ifsc: { labelKey: "wsteps.f.bank_ifsc" }, pan: { labelKey: "wsteps.f.pan" }, aadhaar: { labelKey: "wsteps.f.aadhaar" },
};

const GROUPS: { titleKey: string; keys: string[] }[] = [
  { titleKey: "wsteps.g.personal", keys: ["first_name", "last_name", "preferred_name", "date_of_birth", "phone", "personal_email"] },
  { titleKey: "wsteps.g.address", keys: ["address_line1", "address_line2", "city", "state", "pin_code"] },
  { titleKey: "wsteps.g.emergency", keys: ["emergency_name", "emergency_relation", "emergency_phone"] },
  { titleKey: "wsteps.g.bank", keys: ["bank_account_holder", "bank_account_number", "bank_ifsc", "pan", "aadhaar"] },
];

const EXAMPLES: Record<string, string> = {
  pan: "ABCDE1234F", bank_ifsc: "HDFC0001234", bank_account_number: "123456789012", phone: "+91 98765 43210", emergency_phone: "+91 98765 43210",
  personal_email: "ananya.rao@gmail.com", pin_code: "600040", aadhaar: "1234 5678 9012", city: "Chennai",
};

/** What the dialog shows for a built-in step. `onChanged` reloads the portal (progress). */
export function BuiltinStepBody({ step, token, onChanged, onClose }: { step: Builtin; token: string; onChanged: () => void; onClose: () => void }) {
  const f = useTheme().palette.fresh;
  const { t } = useI18n();
  const d = useDateText();

  if (step.state === "locked") {
    return (
      <Stack spacing={1.5}>
        <Typography sx={{ color: f.muted }}>{t(TEXT_KEYS[step.kind].hintKey)}</Typography>
        <Alert severity="info" icon={<Emoji name="lock" />}>{t("wsteps.locked_long")}</Alert>
      </Stack>
    );
  }

  if (step.kind === "offer") {
    const pdf = step.pdf_url && (
      <Button variant={step.done ? "contained" : "outlined"} size="large" href={step.pdf_url} target="_blank" rel="noopener" startIcon={<Emoji name="page" size={18} />}>
        {step.done ? t("wsteps.offer.view_signed") : t("wsteps.offer.view_pdf")}
      </Button>
    );
    return step.done ? (
      <Stack spacing={1.5}>
        <Alert severity="success">{step.signed_at ? t("wsteps.offer.signed_on", { when: d.long(step.signed_at) }) : t("wsteps.offer.done_note")}</Alert>
        {step.version_no > 1 && <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("wsteps.offer.version", { n: step.version_no })}</Typography>}
        {pdf}
      </Stack>
    ) : (
      <Stack spacing={1.5}>
        {step.version_no > 1 && <Alert severity="info">{t("wsteps.offer.revised", { n: step.version_no })}</Alert>}
        <Typography>{step.method === "docusign" ? t("wsteps.offer.intro_docusign") : t("wsteps.offer.intro")}</Typography>
        {step.expiry_date && <Typography sx={{ fontSize: 14 }}>{t("wsteps.offer.sign_by", { when: d.long(step.expiry_date) })}</Typography>}
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25}>
          {pdf}
          {step.sign_url ? (
            <Button variant="contained" size="large" href={step.sign_url} startIcon={<Emoji name="writing_hand" size={18} />}>{t("wsteps.offer.review_sign")}</Button>
          ) : null}
        </Stack>
        {!step.sign_url && <Alert severity="info">{t("wsteps.offer.no_link")}</Alert>}
        <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("wsteps.offer.after")}</Typography>
      </Stack>
    );
  }

  if (step.kind === "joining_details") return <JoiningDetails step={step} token={token} onChanged={onChanged} onClose={onClose} />;
  if (step.kind === "joining_documents") return <JoiningDocuments docs={step.documents} token={token} onChanged={onChanged} />;
  return <DayOne step={step} token={token} onChanged={onChanged} onClose={onClose} />;
}

function JoiningDetails({ step, token, onChanged, onClose }: { step: Extract<Builtin, { kind: "joining_details" }>; token: string; onChanged: () => void; onClose: () => void }) {
  const f = useTheme().palette.fresh;
  const { t } = useI18n();
  const fields: JoiningField[] = step.fields ?? [];
  const [values, setValues] = useState<Record<string, string>>({ ...(step.saved ?? {}) });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [state, setState] = useState<"idle" | "saving" | "saved" | "failed">("idle");
  const [submitting, setSubmitting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const dirty = useRef<Record<string, string>>({});
  const timer = useRef<number | undefined>(undefined);

  const flush = async () => {
    window.clearTimeout(timer.current);
    const changes = dirty.current;
    if (!Object.keys(changes).length) return;
    dirty.current = {};
    setState("saving");
    try {
      const out = await welcomePortalApi.saveJoiningDetails(token, changes, false);
      setErrors(out.errors || {});
      setState("saved");
    } catch {
      dirty.current = { ...changes, ...dirty.current };
      setState("failed");
    }
  };

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const set = (key: string, v: string) => {
    setValues((prev) => ({ ...prev, [key]: v }));
    dirty.current = { ...dirty.current, [key]: v };
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { void flush(); }, 1200);
  };

  const submit = async () => {
    await flush();
    setSubmitting(true);
    setProblem(null);
    try {
      await welcomePortalApi.saveJoiningDetails(token, values, true);
      onChanged();
      onClose();
    } catch (e) {
      const det = e instanceof ApiError ? (e.detail as { errors?: Record<string, string> } | string) : null;
      if (det && typeof det === "object" && det.errors) {
        setErrors(det.errors);
        setTouched(new Set(Object.keys(det.errors)));
        setProblem(t("wsteps.details.fix_fields", { count: Object.keys(det.errors).length }));
      } else setProblem(t("welcome.save_failed"));
    } finally {
      setSubmitting(false);
    }
  };

  const byKey = Object.fromEntries(fields.map((x) => [x.key, x]));
  return (
    <Stack spacing={2.25} sx={{ pt: 1 }}>
      {step.done && <Alert severity="success">{t("wsteps.details.sent_before")}</Alert>}
      <Typography sx={{ color: f.muted, fontSize: 13 }} role="status" aria-live="polite">
        {state === "saving" ? t("wsteps.autosave.saving") : state === "saved" ? t("wsteps.autosave.saved") : state === "failed" ? t("wsteps.autosave.failed") : t("wsteps.autosave.hint")}
      </Typography>
      {GROUPS.map((g) => (
        <Box key={g.titleKey}>
          <Typography component="h3" sx={{ fontWeight: 700, mb: 1 }}>{t(g.titleKey)}</Typography>
          {g.titleKey === "wsteps.g.bank" && <Typography sx={{ color: f.muted, fontSize: 13, mb: 1 }}>{t("wsteps.bank_private")}</Typography>}
          <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" } }}>
            {g.keys.filter((k) => byKey[k]).map((k) => {
              const fl = byKey[k];
              const err = touched.has(k) || values[k] ? errors[k] : undefined;
              const label = FIELD_KEYS[k] ? t(FIELD_KEYS[k].labelKey) : fl.label;
              return (
                <TextField
                  key={k} fullWidth label={label} required={fl.required} value={values[k] ?? ""}
                  type={fl.kind === "date" ? "date" : fl.kind === "email" ? "email" : "text"}
                  placeholder={EXAMPLES[k] ?? ""}
                  inputMode={fl.kind === "phone" || fl.kind === "pin" || fl.kind === "bank_account" || fl.kind === "aadhaar" ? "numeric" : undefined}
                  onChange={(e) => set(k, e.target.value)}
                  onFocus={(e) => { if (fl.sensitive && /X/.test(values[k] ?? "")) e.target.select(); }}
                  onBlur={() => { setTouched((p) => new Set(p).add(k)); void flush(); }}
                  error={Boolean(err)}
                  helperText={err || (fl.sensitive && /X/.test(values[k] ?? "") ? t("wsteps.masked_hint") : fl.required ? t("welcome.form.required") : t("welcome.form.optional"))}
                  slotProps={fl.kind === "date" ? { inputLabel: { shrink: true } } : undefined}
                />
              );
            })}
          </Box>
        </Box>
      ))}
      {problem && <Alert severity="warning">{problem}</Alert>}
      <Stack direction="row" justifyContent="flex-end">
        <Button variant="contained" size="large" onClick={submit} disabled={submitting}>{submitting ? t("welcome.saving") : t("wsteps.details.submit")}</Button>
      </Stack>
    </Stack>
  );
}

function JoiningDocuments({ docs, token, onChanged }: { docs: JoiningDoc[]; token: string; onChanged: () => void }) {
  const f = useTheme().palette.fresh;
  const { t } = useI18n();
  const [openCode, setOpenCode] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  if (!docs.length) return <Typography sx={{ color: f.muted }}>{t("wsteps.docs.none")}</Typography>;
  const statusText = (x: JoiningDoc) =>
    x.status === "verified" ? t("welcome.step.doc_verified") : x.status === "uploaded" ? t("welcome.step.doc_uploaded")
      : x.status === "received_earlier" ? t("wsteps.docs.received_earlier") : x.status === "rejected" ? t("welcome.step.doc_again") : t("welcome.step.doc_todo");
  return (
    <Stack spacing={1.25} sx={{ pt: 1 }}>
      <Typography sx={{ color: f.muted }}>{t("wsteps.docs.intro")}</Typography>
      {docs.map((x) => {
        const done = x.status !== "missing" && x.status !== "rejected";
        return (
          <Box key={x.code} sx={{ border: `1px solid ${x.status === "rejected" ? f.coral : f.line}`, borderRadius: "12px", p: 1.5, bgcolor: done ? f.okSoft : f.surface2 }}>
            <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1} flexWrap="wrap" useFlexGap>
              <Box>
                <Typography sx={{ fontWeight: 700 }}>{x.label}{x.required ? "" : ` (${t("welcome.form.optional")})`}</Typography>
                <Typography sx={{ fontSize: 13, color: x.status === "rejected" ? f.coral : f.muted }}>{statusText(x)}{done ? " ✓" : ""}</Typography>
                {x.status === "rejected" && x.rejection_reason && <Typography sx={{ fontSize: 13 }}>{t("welcome.doc.hr_said", { reason: x.rejection_reason })}</Typography>}
              </Box>
              {x.status !== "verified" && (
                <Button variant={done ? "text" : "contained"} onClick={() => setOpenCode(openCode === x.code ? null : x.code)}>
                  {done ? t("wsteps.docs.replace") : t("wsteps.docs.upload")}
                </Button>
              )}
            </Stack>
            {openCode === x.code && (
              <Box sx={{ mt: 1.5 }}>
                <DocumentCapture
                  label={x.label}
                  onUpload={async (blob, filename) => {
                    setProblem(null);
                    try {
                      await welcomePortalApi.uploadJoiningDocument(token, x.code, blob, filename);
                    } catch (e) {
                      const msg = e instanceof ApiError && typeof e.detail === "string" ? e.detail : t("welcome.save_failed");
                      setProblem(msg);
                      throw e;
                    }
                    setOpenCode(null);
                    onChanged();
                  }}
                />
              </Box>
            )}
          </Box>
        );
      })}
      {problem && <Alert severity="warning">{problem}</Alert>}
    </Stack>
  );
}

function DayOne({ step, token, onChanged, onClose }: { step: Extract<Builtin, { kind: "day_one" }>; token: string; onChanged: () => void; onClose: () => void }) {
  const f = useTheme().palette.fresh;
  const { t } = useI18n();
  const d = useDateText();
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const info = step.info;
  if (!info) return null;
  const row = (emoji: string, title: string, body: React.ReactNode) => (
    <Stack direction="row" spacing={1.25} alignItems="flex-start">
      <Emoji name={emoji} size={22} />
      <Box><Typography sx={{ fontWeight: 700 }}>{title}</Typography><Box sx={{ color: f.ink }}>{body}</Box></Box>
    </Stack>
  );
  const ack = async () => {
    setSaving(true);
    setProblem(null);
    try {
      await welcomePortalApi.acknowledgeDayOne(token);
      onChanged();
      onClose();
    } catch {
      setProblem(t("welcome.save_failed"));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Stack spacing={2} sx={{ pt: 1 }}>
      {row("calendar", t("wsteps.day1.when"), <Typography>{d.long(info.date)}{info.start_time ? ` · ${info.start_time}` : ""}</Typography>)}
      {row("house", t("wsteps.day1.where"), info.address ? (
        <>
          <Typography sx={{ whiteSpace: "pre-line" }}>{info.address}</Typography>
          {info.map_url && <Button size="small" href={info.map_url} target="_blank" rel="noopener" sx={{ px: 0 }}>{t("wsteps.day1.open_map")}</Button>}
        </>
      ) : <Typography sx={{ color: f.muted }}>{t("wsteps.day1.address_soon")}</Typography>)}
      {info.meet && row("people", t("wsteps.day1.meet"), <Typography>{info.meet}</Typography>)}
      {info.what_to_bring.length > 0 && row("clipboard", t("wsteps.day1.bring"), (
        <Box component="ul" sx={{ m: 0, pl: 2.5 }}>{info.what_to_bring.map((x, i) => <li key={i}>{x}</li>)}</Box>
      ))}
      {info.agenda.length > 0 && row("alarm_clock", t("welcome.first_day"), (
        <Box component="ul" sx={{ m: 0, pl: 2.5 }}>{info.agenda.map((x, i) => <li key={i}>{x.time ? `${x.time} - ` : ""}{x.title}</li>)}</Box>
      ))}
      {info.acknowledged_at && <Alert severity="success">{t("wsteps.day1.done_note")}</Alert>}
      {problem && <Alert severity="warning">{problem}</Alert>}
      {!info.acknowledged_at && (
        <Stack direction="row" justifyContent="flex-end">
          <Button variant="contained" size="large" onClick={ack} disabled={saving}>{t("wsteps.day1.got_it")}</Button>
        </Stack>
      )}
    </Stack>
  );
}

/** People you can reach out to -- only people HR has set up; empty lines are never shown. */
export function ContactsCard({ contacts }: { contacts: PortalContact[] }) {
  const f = useTheme().palette.fresh;
  const { t } = useI18n();
  if (!contacts.length) return null;
  return (
    <Card sx={{ p: { xs: 2, md: 2.5 } }}>
      <Typography component="h2" sx={{ fontWeight: 700, fontSize: 16, mb: 1.5 }}>{t("wsteps.contacts.title")}</Typography>
      <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", md: "repeat(3, minmax(0, 1fr))" } }}>
        {contacts.map((c, i) => (
          <Stack key={i} direction="row" spacing={1.25} alignItems="center" sx={{ p: 1.25, borderRadius: "12px", bgcolor: f.surface2 }}>
            <UserAvatar name={c.name} size={44} />
            <Box sx={{ minWidth: 0 }}>
              <Typography sx={{ fontWeight: 700 }}>{c.name}</Typography>
              {c.role && <Typography sx={{ fontSize: 13, color: f.muted }}>{c.role}</Typography>}
              {c.email && <Typography component="a" href={`mailto:${c.email}`} sx={{ fontSize: 13, display: "block", overflowWrap: "anywhere" }}>{c.email}</Typography>}
              {c.phone && <Typography component="a" href={`tel:${c.phone.replace(/\s/g, "")}`} sx={{ fontSize: 13, display: "block" }}>{c.phone}</Typography>}
            </Box>
          </Stack>
        ))}
      </Box>
    </Card>
  );
}
