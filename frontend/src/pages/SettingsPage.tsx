import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { ApiError, integrationsApi } from "../api/client";
import type { IntegrationStatus } from "../api/types";

export default function SettingsPage() {
  const [status, setStatus] = useState<IntegrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = () => {
    setLoading(true);
    integrationsApi
      .googleStatus()
      .then(setStatus)
      .catch((err) => setError(err instanceof ApiError ? String(err.detail) : "Failed to load connection status"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadStatus();
    // The Google OAuth callback lands on a page served by the backend, not this app --
    // re-check status whenever the user comes back to this tab so "Connected" shows up
    // without requiring a manual refresh.
    const handleFocus = () => loadStatus();
    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
  }, []);

  const handleConnect = async () => {
    setConnecting(true);
    setError(null);
    try {
      const { auth_url } = await integrationsApi.connectGoogle();
      window.location.href = auth_url;
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Failed to start Google connection");
      setConnecting(false);
    }
  };

  return (
    <Box>
      <Typography variant="h4" mb={3}>
        Settings
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Card variant="outlined" sx={{ maxWidth: 480 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Google Calendar
          </Typography>
          <Typography variant="body2" color="text.secondary" mb={2}>
            Connect your Google account so interviews scheduled for you create a real Calendar
            event with an invite, instead of relying on a manually pasted meeting link.
          </Typography>

          {loading ? (
            <CircularProgress size={24} />
          ) : (
            <Stack direction="row" spacing={2} alignItems="center">
              <Chip
                label={status?.connected ? "Connected" : "Not connected"}
                color={status?.connected ? "success" : "default"}
                size="small"
              />
              {status?.connected && status.connected_at && (
                <Typography variant="body2" color="text.secondary">
                  since {new Date(status.connected_at).toLocaleString()}
                </Typography>
              )}
              {!status?.connected && (
                <Button size="small" variant="contained" onClick={handleConnect} disabled={connecting}>
                  {connecting ? "Redirecting..." : "Connect Google Calendar"}
                </Button>
              )}
            </Stack>
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
