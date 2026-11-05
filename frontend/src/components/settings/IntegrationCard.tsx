import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import type { IntegrationStatus } from "../../api/types";
import { useT } from "../../i18n";
import { Emoji, FriendlyError, StatusChip } from "../../ui-kit";

// One personal account connection (Google Calendar / DocuSign / LinkedIn). Behaviour is
// unchanged from the old SettingsPage card: status on mount + on window focus (the OAuth
// callback lands on a backend page), Connect / Reconnect redirects to the provider.
export default function IntegrationCard({
  emoji,
  title,
  description,
  connectLabel,
  fetchStatus,
  connect,
}: {
  emoji: string;
  title: string;
  description: string;
  connectLabel: string;
  fetchStatus: () => Promise<IntegrationStatus>;
  connect: () => Promise<{ auth_url: string }>;
}) {
  const f = useTheme().palette.fresh;
  const t = useT();
  const [status, setStatus] = useState<IntegrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const loadStatus = () => {
    setLoading(true);
    fetchStatus()
      .then((s) => {
        setStatus(s);
        setError(null);
      })
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadStatus();
    // The OAuth callback lands on a page served by the backend, not this app -- re-check
    // status whenever the user comes back to this tab so "Connected" shows up without
    // requiring a manual refresh.
    const handleFocus = () => loadStatus();
    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleConnect = async () => {
    setConnecting(true);
    setError(null);
    try {
      const { auth_url } = await connect();
      window.location.href = auth_url;
    } catch (err) {
      setError(err);
      setConnecting(false);
    }
  };

  const chip = !status?.connected ? (
    <StatusChip tone="muted" emoji="link" label={t("settingsPage.integration.not_connected")} />
  ) : status.expired ? (
    <StatusChip tone="sun" emoji="alarm_clock" label={t("settingsPage.integration.expired")} />
  ) : (
    <StatusChip tone="ok" emoji="check" label={t("settingsPage.integration.connected")} />
  );

  return (
    <Card sx={{ p: 2.5 }}>
      <Stack direction="row" spacing={1.5} alignItems="flex-start">
        <Box sx={{ width: 42, height: 42, borderRadius: "12px", bgcolor: f.brandSoft, display: "grid", placeItems: "center", flexShrink: 0 }}>
          <Emoji name={emoji} size={22} />
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography component="h3" sx={{ fontWeight: 700, fontSize: 16 }}>{title}</Typography>
          <Typography sx={{ color: f.muted, mt: 0.5, mb: 1.5 }}>{description}</Typography>

          {error !== null && (
            <Box sx={{ mb: 1.5 }}>
              <FriendlyError error={error} onRetry={loadStatus} compact />
            </Box>
          )}

          {loading ? (
            <CircularProgress size={24} aria-label={t("settingsPage.loading")} />
          ) : (
            <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
              {chip}
              {status?.connected && status.connected_at && (
                <Typography variant="body2" sx={{ color: f.muted }}>
                  {t("settingsPage.integration.since", { when: new Date(status.connected_at).toLocaleString() })}
                </Typography>
              )}
              {status?.expired && (
                <Typography variant="body2" sx={{ color: f.muted }}>
                  {t("settingsPage.integration.expired_hint")}
                </Typography>
              )}
              {(!status?.connected || status.expired) && (
                <Button size="small" variant="contained" onClick={handleConnect} disabled={connecting}>
                  {connecting
                    ? t("settingsPage.integration.redirecting")
                    : status?.expired
                      ? t("settingsPage.integration.reconnect", { name: title })
                      : connectLabel}
                </Button>
              )}
            </Stack>
          )}
        </Box>
      </Stack>
    </Card>
  );
}
