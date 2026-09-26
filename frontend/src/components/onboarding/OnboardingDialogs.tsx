import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import { useTheme } from "@mui/material/styles";


import { onboardingExtraApi, welcomeLink, type ReadyOffer, type WelcomeContent } from "../../api/onboardingExtra";
import { useT } from "../../i18n";
import { Emoji, explainError, InfoTip } from "../../ui-kit";
import { useDateText } from "./shared";

function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  const e = explainError(error);
  return <Alert severity="error" sx={{ mt: 1 }}><b>{e.what}</b> {e.fix}</Alert>;
}

const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// ---- the portal link (shown once after creating / making a new link) ----

export function LinkDialog({ token, name, onClose }: { token: string | null; name: string; onClose: () => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [copied, setCopied] = useState(false);
  const link = token ? welcomeLink(token) : "";
  useEffect(() => setCopied(false), [token]);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <Dialog open={Boolean(token)} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle><Emoji name="link" /> {t("onboarding.link.title", { name })}</DialogTitle>
      <DialogContent>
        <Typography sx={{ color: f.muted, mb: 1.5 }}>{t("onboarding.link.body")}</Typography>
        <TextField value={link} fullWidth label={t("onboarding.link.label")} slotProps={{ input: { readOnly: true } }} onFocus={(e) => e.target.select()} />
        <Typography sx={{ fontSize: 12, color: f.muted, mt: 1 }}>{t("onboarding.link.hint")}</Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.close")}</Button>
        <Button variant="contained" onClick={copy}>{copied ? t("onboarding.link.copied") : t("onboarding.link.copy")}</Button>
      </DialogActions>
    </Dialog>
  );
}

// ---- start onboarding: from a signed offer, or by hand ----

export function StartDialog({ open, offers, onClose, onCreated }: { open: boolean; offers: ReadyOffer[]; onClose: () => void; onCreated: (token: string, name: string) => void }) {
  const t = useT();
  const d = useDateText();
  const [mode, setMode] = useState<"offer" | "manual">(offers.length ? "offer" : "manual");
  const [offerId, setOfferId] = useState("");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const [date, setDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (open) {
      setMode(offers.length ? "offer" : "manual");
      setOfferId(offers[0]?.offer_id ?? "");
      setFirst(""); setLast(""); setEmail(""); setDate(""); setError(null);
    }
  }, [open, offers]);

  const offer = offers.find((o) => o.offer_id === offerId);
  const needsDate = mode === "offer" ? !offer?.joining_date : true;
  const valid = mode === "offer" ? Boolean(offerId) && (!needsDate || Boolean(date)) : Boolean(first.trim() && /\S+@\S+\.\S+/.test(email) && date);

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = mode === "offer"
        ? await onboardingExtraApi.createCase({ offer_id: offerId, joining_date: date || undefined })
        : await onboardingExtraApi.createCase({ first_name: first.trim(), last_name: last.trim() || undefined, email: email.trim(), joining_date: date });
      onCreated(res.portal_token, mode === "offer" ? offer?.name ?? "" : `${first} ${last}`.trim());
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle><Emoji name="waving_hand" /> {t("onboarding.start.title")}</DialogTitle>
      <DialogContent>
        <Tabs value={mode} onChange={(_, v) => setMode(v)} sx={{ mb: 2 }}>
          <Tab value="offer" label={t("onboarding.start.from_offer", { count: offers.length })} disabled={!offers.length} />
          <Tab value="manual" label={t("onboarding.start.by_hand")} />
        </Tabs>
        {mode === "offer" ? (
          <Stack spacing={2}>
            <TextField select label={t("onboarding.start.offer")} value={offerId} onChange={(e) => setOfferId(e.target.value)} helperText={t("onboarding.start.offer_hint")}>
              {offers.map((o) => (
                <MenuItem key={o.offer_id} value={o.offer_id}>
                  {o.name}{o.role ? ` · ${o.role}` : ""}{o.joining_date ? ` · ${d.day(o.joining_date)}` : ""}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              type="date" label={t("onboarding.start.date")} value={date} onChange={(e) => setDate(e.target.value)}
              slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: todayIso() } }}
              helperText={needsDate ? t("onboarding.start.date_needed") : t("onboarding.start.date_optional")}
            />
          </Stack>
        ) : (
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField label={t("onboarding.start.first")} placeholder={t("onboarding.start.first_ph")} value={first} onChange={(e) => setFirst(e.target.value)} fullWidth required helperText={t("onboarding.start.first_hint")} />
              <TextField label={t("onboarding.start.last")} placeholder={t("onboarding.start.last_ph")} value={last} onChange={(e) => setLast(e.target.value)} fullWidth helperText={t("onboarding.start.optional")} />
            </Stack>
            <TextField type="email" label={t("onboarding.start.email")} placeholder="ananya.rao@gmail.com" value={email} onChange={(e) => setEmail(e.target.value)} required helperText={t("onboarding.start.email_hint")} />
            <TextField
              type="date" label={t("onboarding.start.date")} value={date} onChange={(e) => setDate(e.target.value)} required
              slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: todayIso() } }} helperText={t("onboarding.start.date_hint")}
            />
          </Stack>
        )}
        <ErrorLine error={error} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" disabled={!valid || saving} onClick={submit}>{saving ? t("onboarding.saving") : t("onboarding.start.submit")}</Button>
      </DialogActions>
    </Dialog>
  );
}

// ---- change joining date ----

export function DateDialog({ open, name, current, onClose, onSave }: { open: boolean; name: string; current: string; onClose: () => void; onSave: (date: string, reason: string) => Promise<void> }) {
  const t = useT();
  const [date, setDate] = useState(current);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (open) { setDate(current); setReason(""); setError(null); }
  }, [open, current]);
  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(date, reason);
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle><Emoji name="calendar" /> {t("onboarding.date.title", { name })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField type="date" label={t("onboarding.start.date")} value={date} onChange={(e) => setDate(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} helperText={t("onboarding.date.hint")} />
          <TextField label={t("onboarding.date.reason")} placeholder={t("onboarding.date.reason_ph")} value={reason} onChange={(e) => setReason(e.target.value)} helperText={t("onboarding.start.optional")} />
        </Stack>
        <ErrorLine error={error} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" disabled={!date || date === current || saving} onClick={save}>{t("action.save")}</Button>
      </DialogActions>
    </Dialog>
  );
}

// ---- no-show / withdraw (both close the joiner, so a reason is asked) ----

export function CloseDialog({ kind, name, onClose, onConfirm }: { kind: "no_show" | "revoke" | null; name: string; onClose: () => void; onConfirm: (reason: string) => Promise<void> }) {
  const t = useT();
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (kind) { setReason(""); setError(null); }
  }, [kind]);
  const go = async () => {
    setSaving(true);
    setError(null);
    try {
      await onConfirm(reason);
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog open={Boolean(kind)} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{kind === "revoke" ? t("onboarding.close.revoke_title", { name }) : t("onboarding.close.no_show_title", { name })}</DialogTitle>
      <DialogContent>
        <Typography sx={{ mb: 2 }}>{kind === "revoke" ? t("onboarding.close.revoke_body") : t("onboarding.close.no_show_body")}</Typography>
        <TextField label={t("onboarding.close.reason")} placeholder={t("onboarding.close.reason_ph")} value={reason} onChange={(e) => setReason(e.target.value)} fullWidth helperText={t("onboarding.close.reason_hint")} />
        <ErrorLine error={error} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" color="error" disabled={saving} onClick={go}>{kind === "revoke" ? t("onboarding.action.revoke") : t("onboarding.action.no_show")}</Button>
      </DialogActions>
    </Dialog>
  );
}

// ---- reject a document (the joiner sees the reason) ----

export function RejectDialog({ label, onClose, onConfirm }: { label: string | null; onClose: () => void; onConfirm: (reason: string) => Promise<void> }) {
  const t = useT();
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (label) { setReason(""); setError(null); }
  }, [label]);
  const go = async () => {
    setSaving(true);
    try {
      await onConfirm(reason.trim());
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog open={Boolean(label)} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{t("onboarding.docs.reject_title", { label: label ?? "" })}</DialogTitle>
      <DialogContent>
        <TextField
          autoFocus multiline minRows={2} fullWidth label={t("onboarding.docs.reason")} placeholder={t("onboarding.docs.reason_ph")}
          value={reason} onChange={(e) => setReason(e.target.value)} helperText={t("onboarding.docs.reason_hint")} sx={{ mt: 1 }}
        />
        <ErrorLine error={error} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" color="error" disabled={!reason.trim() || saving} onClick={go}>{t("onboarding.docs.reject")}</Button>
      </DialogActions>
    </Dialog>
  );
}

// ---- welcome content: personal message, buddy, first-day agenda ----

export function WelcomeEditor({ initial, onSave }: { initial: WelcomeContent; onSave: (w: WelcomeContent) => Promise<void> }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [message, setMessage] = useState(initial.message ?? "");
  const [buddyName, setBuddyName] = useState(initial.buddy?.name ?? "");
  const [buddyTitle, setBuddyTitle] = useState(initial.buddy?.title ?? "");
  const [buddyNote, setBuddyNote] = useState(initial.buddy?.note ?? "");
  const [buddyEmail, setBuddyEmail] = useState(initial.buddy?.email ?? "");
  const [agenda, setAgenda] = useState(initial.agenda.length ? initial.agenda : []);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const setRow = (i: number, patch: Partial<WelcomeContent["agenda"][number]>) => setAgenda((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const save = async () => {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await onSave({
        message: message.trim() || null,
        buddy: buddyName.trim() ? { name: buddyName.trim(), title: buddyTitle.trim() || null, note: buddyNote.trim() || null, email: buddyEmail.trim() || null } : null,
        agenda: agenda.filter((a) => a.title.trim()).map((a) => ({ time: a.time?.trim() || null, title: a.title.trim(), emoji: a.emoji || null })),
      });
      setSaved(true);
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack spacing={2}>
      <TextField
        label={t("onboarding.welcome.message")} placeholder={t("onboarding.welcome.message_ph")} multiline minRows={2}
        value={message} onChange={(e) => setMessage(e.target.value)} helperText={t("onboarding.welcome.message_hint")}
      />
      <Typography sx={{ fontWeight: 700 }}>
        <Emoji name="handshake" /> {t("onboarding.welcome.buddy")}
        <InfoTip text={t("onboarding.welcome.buddy_tip")} />
      </Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
        <TextField label={t("onboarding.welcome.buddy_name")} placeholder="Meera S" value={buddyName} onChange={(e) => setBuddyName(e.target.value)} fullWidth helperText={t("onboarding.welcome.buddy_name_hint")} />
        <TextField label={t("onboarding.welcome.buddy_title")} placeholder={t("onboarding.welcome.buddy_title_ph")} value={buddyTitle} onChange={(e) => setBuddyTitle(e.target.value)} fullWidth helperText={t("onboarding.start.optional")} />
      </Stack>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
        <TextField label={t("onboarding.welcome.buddy_note")} placeholder={t("onboarding.welcome.buddy_note_ph")} value={buddyNote} onChange={(e) => setBuddyNote(e.target.value)} fullWidth helperText={t("onboarding.welcome.buddy_note_hint")} />
        <TextField type="email" label={t("onboarding.welcome.buddy_email")} placeholder="meera.s@yourcompany.com" value={buddyEmail} onChange={(e) => setBuddyEmail(e.target.value)} fullWidth helperText={t("onboarding.welcome.buddy_email_hint")} />
      </Stack>
      <Typography sx={{ fontWeight: 700 }}><Emoji name="calendar" /> {t("onboarding.welcome.agenda")}</Typography>
      {agenda.length === 0 && <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("onboarding.welcome.agenda_empty")}</Typography>}
      {agenda.map((row, i) => (
        <Stack key={i} direction="row" spacing={1} alignItems="flex-start">
          <TextField label={t("onboarding.welcome.time")} placeholder="9:30" value={row.time ?? ""} onChange={(e) => setRow(i, { time: e.target.value })} sx={{ width: 110 }} />
          <TextField label={t("onboarding.welcome.what")} placeholder={t("onboarding.welcome.what_ph")} value={row.title} onChange={(e) => setRow(i, { title: e.target.value })} fullWidth />
          <IconButton aria-label={t("action.remove")} onClick={() => setAgenda((rows) => rows.filter((_, j) => j !== i))} sx={{ mt: 1 }}><DeleteOutlineIcon /></IconButton>
        </Stack>
      ))}
      <Box>
        <Button size="small" disabled={agenda.length >= 12} onClick={() => setAgenda((rows) => [...rows, { time: "", title: "", emoji: null }])}>＋ {t("onboarding.welcome.add_item")}</Button>
      </Box>
      <ErrorLine error={error} />
      <Stack direction="row" spacing={1} alignItems="center">
        <Button variant="contained" onClick={save} disabled={saving}>{saving ? t("onboarding.saving") : t("onboarding.welcome.save")}</Button>
        {saved && <Typography sx={{ color: f.ok, fontWeight: 700 }}><Emoji name="check" size={16} /> {t("onboarding.welcome.saved")}</Typography>}
      </Stack>
    </Stack>
  );
}
