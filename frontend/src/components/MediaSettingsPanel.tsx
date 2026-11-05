import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, mediaApi, type MediaItem } from "../api/client";
import { useT } from "../i18n";
import { Emoji, InfoTip, refreshMediaCache, StatusChip } from "../ui-kit";

// Part 15 B / L-V4: Settings -> "Welcome video & tours". The company uploads the pre-joiner
// welcome video/GIF and a 20-40s "Show me how" loop per page (MP4/WebM, GIF as fallback).

export const TOUR_PAGES: { key: string; labelKey: string; emoji: string }[] = [
  { key: "home", labelKey: "nav.overview", emoji: "house" },
  { key: "approvals", labelKey: "nav.approvals", emoji: "check" },
  { key: "jobs", labelKey: "nav.jobs", emoji: "briefcase" },
  { key: "candidates", labelKey: "nav.candidates", emoji: "technologist" },
  { key: "screening", labelKey: "nav.screening", emoji: "magnifier" },
  { key: "shortlisting", labelKey: "nav.shortlisting", emoji: "star" },
  { key: "interviews", labelKey: "nav.interviews", emoji: "calendar" },
  { key: "hr-inbox", labelKey: "nav.hr_inbox", emoji: "inbox" },
  { key: "salary", labelKey: "nav.salary", emoji: "money" },
  { key: "bgv", labelKey: "nav.bgv", emoji: "shield" },
  { key: "offers", labelKey: "nav.offers", emoji: "envelope" },
  { key: "onboarding", labelKey: "nav.onboarding", emoji: "waving_hand" },
  { key: "employees", labelKey: "nav.employees", emoji: "people" },
  { key: "performance", labelKey: "nav.performance", emoji: "target" },
  { key: "helpdesk", labelKey: "nav.helpdesk", emoji: "ring_buoy" },
  { key: "assets", labelKey: "nav.assets", emoji: "laptop" },
  { key: "exits", labelKey: "nav.exits", emoji: "door" },
  { key: "reports", labelKey: "nav.reports", emoji: "bar_chart" },
  { key: "settings", labelKey: "nav.settings", emoji: "gear" },
];

const ACCEPT = "video/mp4,video/webm,image/gif,image/png,image/jpeg,image/webp";

function MediaRow({ mediaKey, label, emoji, hint, item, onChanged }: {
  mediaKey: string; label: string; emoji: string; hint: string; item?: MediaItem; onChanged: () => void;
}) {
  const t = useT();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upload = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      await mediaApi.upload(mediaKey, file, label);
      onChanged();
    } catch (err) {
      setError(extractErrorMessage(err, t("media.upload_failed")));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setBusy(true);
    try {
      await mediaApi.remove(mediaKey);
      onChanged();
    } catch (err) {
      setError(extractErrorMessage(err, t("media.upload_failed")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box sx={{ py: 1.5, borderTop: 1, borderColor: "divider" }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }} justifyContent="space-between">
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minWidth: 0 }}>
          <Emoji name={emoji} size={22} />
          <Box sx={{ minWidth: 0 }}>
            <Typography fontWeight={700}>{label}</Typography>
            <Typography variant="body2" color="text.secondary">
              {item ? `${item.content_type.startsWith("video/") ? t("media.video") : t("media.image")} · ${(item.size_bytes / (1024 * 1024)).toFixed(1)} MB` : hint}
            </Typography>
          </Box>
        </Stack>
        <Stack direction="row" spacing={1} alignItems="center">
          {item ? <StatusChip status="done" label={t("media.uploaded")} /> : <StatusChip tone="muted" emoji="hourglass" label={t("media.missing")} />}
          {item && (
            <Button size="small" component="a" href={mediaApi.fileUrl(mediaKey)} target="_blank" rel="noopener">
              {t("action.watch")}
            </Button>
          )}
          {item && <Button size="small" color="error" disabled={busy} onClick={remove}>{t("action.remove")}</Button>}
          <Button size="small" variant={item ? "outlined" : "contained"} disabled={busy} onClick={() => input.current?.click()}>
            {busy ? t("media.uploading") : item ? t("action.replace") : t("action.upload")}
          </Button>
          <input ref={input} type="file" accept={ACCEPT} hidden onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) void upload(file);
          }} />
        </Stack>
      </Stack>
      {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}
    </Box>
  );
}

export default function MediaSettingsPanel() {
  const t = useT();
  const [items, setItems] = useState<MediaItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = () => {
    refreshMediaCache();
    mediaApi.list().then(setItems).catch((err) => setLoadError(extractErrorMessage(err, t("media.load_failed"))));
  };
  useEffect(load, []);

  const byKey = new Map(items.map((m) => [m.key, m]));
  const uploaded = TOUR_PAGES.filter((p) => byKey.has(`tour.${p.key}`)).length;

  return (
    <Card id="settings-media">
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center" mb={0.5}>
          <Emoji name="clapper" size={22} />
          <Typography variant="h6">{t("media.title")}</Typography>
          <InfoTip text={t("media.info")} />
        </Stack>
        <Typography color="text.secondary" mb={1.5}>
          {t("media.intro", { done: uploaded, total: TOUR_PAGES.length })}
        </Typography>
        {loadError && <Alert severity="error" sx={{ mb: 1 }}>{loadError}</Alert>}
        <MediaRow mediaKey="welcome.video" label={t("media.welcome")} emoji="waving_hand"
          hint={t("media.welcome_hint")} item={byKey.get("welcome.video")} onChanged={load} />
        {TOUR_PAGES.map((p) => (
          <MediaRow key={p.key} mediaKey={`tour.${p.key}`} label={t("media.page_clip", { page: t(p.labelKey) })} emoji={p.emoji}
            hint={t("media.page_hint")} item={byKey.get(`tour.${p.key}`)} onChanged={load} />
        ))}
      </CardContent>
    </Card>
  );
}
