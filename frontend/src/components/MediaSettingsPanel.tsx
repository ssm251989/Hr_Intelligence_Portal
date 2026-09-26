import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, mediaApi, type MediaItem } from "../api/client";
import { Emoji, InfoTip, refreshMediaCache, StatusChip } from "../ui-kit";

// Part 15 B / L-V4: Settings -> "Welcome video & tours". The company uploads the pre-joiner
// welcome video/GIF and a 20-40s "Show me how" loop per page (MP4/WebM, GIF as fallback).

export const TOUR_PAGES: { key: string; label: string; emoji: string }[] = [
  { key: "home", label: "Home", emoji: "house" },
  { key: "approvals", label: "Approvals", emoji: "check" },
  { key: "jobs", label: "Jobs", emoji: "briefcase" },
  { key: "candidates", label: "Candidates", emoji: "technologist" },
  { key: "screening", label: "Screening", emoji: "magnifier" },
  { key: "shortlisting", label: "Shortlisting", emoji: "star" },
  { key: "interviews", label: "Interviews", emoji: "calendar" },
  { key: "hr-inbox", label: "HR Inbox", emoji: "inbox" },
  { key: "salary", label: "Salary", emoji: "money" },
  { key: "bgv", label: "Background checks", emoji: "shield" },
  { key: "offers", label: "Offers", emoji: "envelope" },
  { key: "onboarding", label: "Onboarding", emoji: "waving_hand" },
  { key: "employees", label: "Employees", emoji: "people" },
  { key: "performance", label: "Performance", emoji: "target" },
  { key: "helpdesk", label: "Helpdesk", emoji: "ring_buoy" },
  { key: "assets", label: "Assets", emoji: "laptop" },
  { key: "exits", label: "Exits", emoji: "door" },
  { key: "reports", label: "Reports", emoji: "bar_chart" },
  { key: "settings", label: "Settings", emoji: "gear" },
];

const ACCEPT = "video/mp4,video/webm,image/gif,image/png,image/jpeg,image/webp";

function MediaRow({ mediaKey, label, emoji, hint, item, onChanged }: {
  mediaKey: string; label: string; emoji: string; hint: string; item?: MediaItem; onChanged: () => void;
}) {
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
      setError(extractErrorMessage(err, "That didn't work. Please check the file and try again."));
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
      setError(extractErrorMessage(err, "That didn't work. Please check the file and try again."));
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
              {item ? `${item.content_type.startsWith("video/") ? "Video" : "Image"} · ${(item.size_bytes / (1024 * 1024)).toFixed(1)} MB` : hint}
            </Typography>
          </Box>
        </Stack>
        <Stack direction="row" spacing={1} alignItems="center">
          {item ? <StatusChip status="done" label="Uploaded" /> : <StatusChip tone="muted" emoji="hourglass" label="Not added yet" />}
          {item && (
            <Button size="small" component="a" href={mediaApi.fileUrl(mediaKey)} target="_blank" rel="noopener">
              Watch
            </Button>
          )}
          {item && <Button size="small" color="error" disabled={busy} onClick={remove}>Remove</Button>}
          <Button size="small" variant={item ? "outlined" : "contained"} disabled={busy} onClick={() => input.current?.click()}>
            {busy ? "Uploading..." : item ? "Replace" : "Upload"}
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
  const [items, setItems] = useState<MediaItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = () => {
    refreshMediaCache();
    mediaApi.list().then(setItems).catch((err) => setLoadError(extractErrorMessage(err, "Couldn't load your clips. Please refresh the page.")));
  };
  useEffect(load, []);

  const byKey = new Map(items.map((m) => [m.key, m]));
  const uploaded = TOUR_PAGES.filter((p) => byKey.has(`tour.${p.key}`)).length;

  return (
    <Card id="settings-media">
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center" mb={0.5}>
          <Emoji name="clapper" size={22} />
          <Typography variant="h6">Welcome video & tours</Typography>
          <InfoTip text="Short clips people can watch instead of reading. MP4 or WebM works best (up to 50 MB); a GIF is used only if there is no video." />
        </Stack>
        <Typography color="text.secondary" mb={1.5}>
          Add a welcome video for new joiners and a 20-40 second "Show me how" clip for each page. {uploaded} of {TOUR_PAGES.length} pages have a clip.
        </Typography>
        {loadError && <Alert severity="error" sx={{ mb: 1 }}>{loadError}</Alert>}
        <MediaRow mediaKey="welcome.video" label="Welcome video for new joiners" emoji="waving_hand"
          hint="Shown at the top of the new-joiner portal." item={byKey.get("welcome.video")} onChanged={load} />
        {TOUR_PAGES.map((p) => (
          <MediaRow key={p.key} mediaKey={`tour.${p.key}`} label={`Show me how: ${p.label}`} emoji={p.emoji}
            hint="Plays when someone clicks Show me how on this page." item={byKey.get(`tour.${p.key}`)} onChanged={load} />
        ))}
      </CardContent>
    </Card>
  );
}
