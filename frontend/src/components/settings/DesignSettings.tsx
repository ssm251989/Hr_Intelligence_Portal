import { useCallback, useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonBase from "@mui/material/ButtonBase";
import Card from "@mui/material/Card";
import FormControlLabel from "@mui/material/FormControlLabel";
import Grid from "@mui/material/Grid";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { apiUrl, extractErrorMessage, http, mediaApi, platformSettingsApi } from "../../api/client";
import { useT } from "../../i18n";

type Mode = "emails" | "letters";
interface Banner { key: string; name: string; url: string; still: string }

const EMAIL_KEYS = ["emails.emoji", "emails.animated", "emails.banner_offer", "emails.banner_welcome"];
const LETTER_KEYS = ["letters.signatory_name", "letters.signatory_designation", "letters.watermark", "letters.celebration", "letters.brand_colour", "org.address", "org.cin"];
const LETTER_KINDS = ["offer", "joining", "appointment", "confirmation", "relieving", "experience"];

// Part 22.6c: Settings > Communication > Email design (offer / welcome / exit emails) and
// Settings > Onboarding & employees > Letters (PDF letters). Live preview with sample data, Send test to me,
// banner gallery + own upload, emoji / animation, signatory + signature upload, address / CIN.
export default function DesignSettings({ mode }: { mode: Mode }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const keys = mode === "emails" ? EMAIL_KEYS : LETTER_KEYS;
  const [vals, setVals] = useState<Record<string, unknown> | null>(null);
  const [saved, setSaved] = useState<Record<string, unknown>>({});
  const [emails, setEmails] = useState<{ key: string; name: string }[]>([]);
  const [banners, setBanners] = useState<Banner[]>([]);
  const [which, setWhich] = useState(mode === "emails" ? "recruitment.offer_letter_auto" : "offer");
  const [preview, setPreview] = useState<{ subject?: string; html?: string; text?: string; pdf?: string } | null>(null);
  const [showText, setShowText] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const pdfUrl = useRef<string | null>(null);

  const loadAll = useCallback(() => {
    Promise.all([platformSettingsApi.definitions(), platformSettingsApi.values(),
      mode === "emails" ? http.get<{ emails: { key: string; name: string }[]; banners: Banner[] }>("/api/v1/ui/design/emails") : Promise.resolve(null)])
      .then(([defs, values, list]) => {
        const v: Record<string, unknown> = {};
        for (const k of keys) v[k] = values.find((x) => x.key === k && x.scope_type === "tenant")?.value ?? defs.find((d) => d.key === k)?.default ?? "";
        setVals(v);
        setSaved(v);
        if (list) { setEmails(list.emails); setBanners(list.banners); }
      })
      .catch((e) => setMsg({ ok: false, text: extractErrorMessage(e, t("design22.err")) }));
  }, [mode, keys, t]);
  useEffect(loadAll, [loadAll]);

  // live preview (debounced) with the unsaved values
  useEffect(() => {
    if (!vals) return;
    const handle = setTimeout(async () => {
      try {
        if (mode === "emails") {
          setPreview(await http.post<{ subject: string; html: string; text: string }>(`/api/v1/ui/design/emails/${which}/preview`, { overrides: vals }));
        } else {
          const r = await http.postBlob(`/api/v1/ui/design/letters/${which}/preview`, { overrides: vals });
          if (r.blob) {
            if (pdfUrl.current) URL.revokeObjectURL(pdfUrl.current);
            pdfUrl.current = URL.createObjectURL(r.blob);
            setPreview({ pdf: pdfUrl.current });
          }
        }
      } catch (e) {
        setMsg({ ok: false, text: extractErrorMessage(e, t("design22.err")) });
      }
    }, 400);
    return () => clearTimeout(handle);
  }, [vals, which, mode, t]);

  if (!vals) return msg ? <Alert severity="error">{msg.text}</Alert> : <Skeleton variant="rounded" height={420} />;
  const set = (k: string, v: unknown) => setVals((cur) => ({ ...(cur ?? {}), [k]: v }));
  const dirty = keys.some((k) => JSON.stringify(vals[k]) !== JSON.stringify(saved[k]));

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      for (const k of keys) if (JSON.stringify(vals[k]) !== JSON.stringify(saved[k])) await platformSettingsApi.update(k, vals[k]);
      setSaved(vals);
      setMsg({ ok: true, text: t("design22.saved") });
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, t("design22.err")) });
    } finally {
      setBusy(false);
    }
  };
  const sendTest = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await http.post<{ status: string; to: string; error: string | null }>(`/api/v1/ui/design/${mode}/${which}/test`);
      setMsg(r.status === "failed" ? { ok: false, text: r.error || t("design22.err") } : { ok: true, text: t("design22.test_sent", { to: r.to }) });
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, t("design22.err")) });
    } finally {
      setBusy(false);
    }
  };
  const upload = async (key: string, file: File | undefined, after?: (k: string) => void) => {
    if (!file) return;
    try {
      await mediaApi.upload(key, file);
      setMsg({ ok: true, text: t("design22.uploaded") });
      after?.(key);
      loadAll();
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, t("design22.err")) });
    }
  };

  const bannerKey = which === "recruitment.welcome_selected" ? "emails.banner_welcome" : "emails.banner_offer";
  return (
    <Grid container spacing={2.5}>
      <Grid size={{ xs: 12, md: 5 }}>
        <Card sx={{ p: 2.25 }}>
          <Stack spacing={2}>
            <Typography sx={{ fontWeight: 800 }}>{t(mode === "emails" ? "design22.emails_title" : "design22.letters_title")}</Typography>
            <Typography sx={{ fontSize: 13, color: f.muted }}>{t(mode === "emails" ? "design22.emails_intro" : "design22.letters_intro")}</Typography>
            {mode === "emails" ? (
              <>
                <FormControlLabel control={<Switch checked={vals["emails.emoji"] !== false} onChange={(e) => set("emails.emoji", e.target.checked)} />} label={t("design22.emoji")} />
                <FormControlLabel control={<Switch checked={vals["emails.animated"] !== false} onChange={(e) => set("emails.animated", e.target.checked)} />} label={t("design22.animated")} />
                {which !== "employee.exit_letters" && (
                  <Box>
                    <Typography sx={{ fontWeight: 700, fontSize: 14, mb: 1 }}>{t("design22.banner")}</Typography>
                    <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1 }}>
                      {[...banners, { key: "none", name: t("design22.no_banner"), url: "", still: "" }].map((b) => (
                        <ButtonBase key={b.key} onClick={() => set(bannerKey, b.key)} aria-pressed={vals[bannerKey] === b.key} data-testid={`banner-${b.key}`}
                          sx={{ display: "block", borderRadius: "10px", overflow: "hidden", border: `2px solid ${vals[bannerKey] === b.key ? f.brand : f.line}`, textAlign: "left" }}>
                          {b.url ? <Box component="img" src={apiUrl(b.url) ?? ""} alt={b.name} sx={{ width: "100%", display: "block" }} />
                            : <Box sx={{ height: 54, display: "grid", placeItems: "center", bgcolor: f.surface2, fontSize: 13 }}>{b.name}</Box>}
                          <Typography sx={{ fontSize: 12, px: 0.75, py: 0.25 }}>{b.name}</Typography>
                        </ButtonBase>
                      ))}
                    </Box>
                    <Button component="label" size="small" sx={{ mt: 1 }}>
                      {t("design22.upload_banner")}
                      <input hidden type="file" accept="image/gif,image/png,image/jpeg,image/webp"
                        onChange={(e) => { const file = e.target.files?.[0]; const slug = (file?.name ?? "own").toLowerCase().replace(/\.[a-z0-9]+$/, "").replace(/[^a-z0-9]+/g, "-").slice(0, 30) || "own";
                          void upload(`email.banner.${slug}`, file, () => set(bannerKey, `custom:${slug}`)); }} />
                    </Button>
                    <Typography sx={{ fontSize: 12, color: f.muted }}>{t("design22.banner_hint")}</Typography>
                  </Box>
                )}
              </>
            ) : (
              <>
                <TextField size="small" label={t("design22.signatory_name")} value={String(vals["letters.signatory_name"] ?? "")} onChange={(e) => set("letters.signatory_name", e.target.value)} />
                <TextField size="small" label={t("design22.signatory_designation")} value={String(vals["letters.signatory_designation"] ?? "")} onChange={(e) => set("letters.signatory_designation", e.target.value)} />
                <Box>
                  <Button component="label" size="small" variant="outlined">
                    {t("design22.signature_upload")}
                    <input hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => void upload("letters.signature", e.target.files?.[0], () => set("letters.signatory_name", vals["letters.signatory_name"]))} />
                  </Button>
                  <Typography sx={{ fontSize: 12, color: f.muted, mt: 0.5 }}>{t("design22.signature_hint")}</Typography>
                </Box>
                <TextField size="small" multiline minRows={2} label={t("design22.address")} value={String(vals["org.address"] ?? "")} onChange={(e) => set("org.address", e.target.value)} />
                <TextField size="small" label={t("design22.cin")} value={String(vals["org.cin"] ?? "")} onChange={(e) => set("org.cin", e.target.value)} />
                <Stack direction="row" spacing={1.5} alignItems="center">
                  <TextField size="small" type="color" label={t("design22.colour")} value={String(vals["letters.brand_colour"] || "#1d7ed7")}
                    onChange={(e) => set("letters.brand_colour", e.target.value)} sx={{ width: 120 }} />
                  <Button size="small" onClick={() => set("letters.brand_colour", "")}>{t("design22.colour_reset")}</Button>
                </Stack>
                <FormControlLabel control={<Switch checked={vals["letters.watermark"] !== false} onChange={(e) => set("letters.watermark", e.target.checked)} />} label={t("design22.watermark")} />
                <FormControlLabel control={<Switch checked={vals["letters.celebration"] !== false} onChange={(e) => set("letters.celebration", e.target.checked)} />} label={t("design22.celebration")} />
                <Typography sx={{ fontSize: 12, color: f.muted }}>{t("design22.logo_hint")}</Typography>
              </>
            )}
            {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button variant="contained" onClick={save} disabled={busy || !dirty}>{t("design22.save")}</Button>
              <Button variant="outlined" onClick={sendTest} disabled={busy}>{t("design22.test")}</Button>
            </Stack>
          </Stack>
        </Card>
      </Grid>
      <Grid size={{ xs: 12, md: 7 }}>
        <Card sx={{ p: 2 }}>
          <Tabs value={which} onChange={(_, v) => { setWhich(v); setPreview(null); }} variant="scrollable" sx={{ mb: 1.5 }}>
            {mode === "emails"
              ? emails.map((e) => <Tab key={e.key} value={e.key} label={t(`design22.email.${e.key}`)} />)
              : LETTER_KINDS.map((k) => <Tab key={k} value={k} label={t(`design22.letter.${k}`)} />)}
          </Tabs>
          {mode === "emails" && preview?.subject && (
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Typography sx={{ fontSize: 13, flex: 1 }}><b>{t("design22.subject")}:</b> {preview.subject}</Typography>
              <Button size="small" onClick={() => setShowText((x) => !x)}>{showText ? t("design22.show_html") : t("design22.show_text")}</Button>
            </Stack>
          )}
          {!preview ? <Skeleton variant="rounded" height={560} /> : mode === "emails" ? (
            showText
              ? <Box component="pre" sx={{ whiteSpace: "pre-wrap", fontSize: 13, p: 1.5, bgcolor: f.surface2, borderRadius: "10px", m: 0 }}>{preview.text}</Box>
              : <Box component="iframe" title={t("design22.preview")} srcDoc={preview.html} sandbox="" data-testid="design-preview"
                  sx={{ width: "100%", height: 720, border: `1px solid ${f.line}`, borderRadius: "10px", bgcolor: "#eef2f7" }} />
          ) : (
            <Box component="iframe" title={t("design22.preview")} src={preview.pdf} data-testid="design-preview"
              sx={{ width: "100%", height: 760, border: `1px solid ${f.line}`, borderRadius: "10px" }} />
          )}
          <Typography sx={{ fontSize: 12, color: f.muted, mt: 1 }}>{t("design22.sample_note")}</Typography>
        </Card>
      </Grid>
    </Grid>
  );
}
