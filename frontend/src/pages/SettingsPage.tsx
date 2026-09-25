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

import { extractErrorMessage, integrationsApi } from "../api/client";
import type { IntegrationStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import HrMailboxSettingsCard from "../components/HrMailboxSettingsCard";
import InterviewTrackerSettingsCard from "../components/InterviewTrackerSettingsCard";
import PlatformSettingsPanel from "../components/PlatformSettingsPanel";
import ConnectionsPanel from "../components/ConnectionsPanel";
import CommunicationsPanel from "../components/CommunicationsPanel";
import AccessControlPanel from "../components/AccessControlPanel";
import WorkflowsPanel from "../components/WorkflowsPanel";
import MetadataPanel from "../components/MetadataPanel";
import CoreHrPanel from "../components/CoreHrPanel";
import RecruitmentPanel from "../components/RecruitmentPanel";
import OnboardingPanel from "../components/OnboardingPanel";
import PerformancePanel from "../components/PerformancePanel";
import ServiceDeskPanel from "../components/ServiceDeskPanel";
import PrivacyPanel from "../components/PrivacyPanel";
import MfaSettingsCard from "../components/MfaSettingsCard";

function IntegrationCard({
  title,
  description,
  connectLabel,
  fetchStatus,
  connect,
}: {
  title: string;
  description: string;
  connectLabel: string;
  fetchStatus: () => Promise<IntegrationStatus>;
  connect: () => Promise<{ auth_url: string }>;
}) {
  const [status, setStatus] = useState<IntegrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = () => {
    setLoading(true);
    fetchStatus()
      .then(setStatus)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load connection status")))
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
      setError(extractErrorMessage(err, `Failed to start ${title} connection`));
      setConnecting(false);
    }
  };

  return (
    <Card variant="outlined" sx={{ maxWidth: 480 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          {title}
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          {description}
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {loading ? (
          <CircularProgress size={24} />
        ) : (
          <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
            <Chip
              label={status?.connected ? (status.expired ? "Expired" : "Connected") : "Not connected"}
              color={status?.connected ? (status.expired ? "warning" : "success") : "default"}
              size="small"
            />
            {status?.connected && status.connected_at && (
              <Typography variant="body2" color="text.secondary">
                since {new Date(status.connected_at).toLocaleString()}
              </Typography>
            )}
            {status?.expired && (
              <Typography variant="body2" color="text.secondary">
                Your connection expired -- reconnect to keep using this integration.
              </Typography>
            )}
            {(!status?.connected || status.expired) && (
              <Button size="small" variant="contained" onClick={handleConnect} disabled={connecting}>
                {connecting ? "Redirecting..." : status?.expired ? `Reconnect ${title}` : connectLabel}
              </Button>
            )}
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const { can } = useAuth();
  const canManageHrIntegration = can(ROLE_MATRIX.hrIntegrationWrite);
  const canManagePlatformSettings = can(ROLE_MATRIX.platformSettingsWrite);

  return (
    <Box>
      <Typography variant="h4" mb={3}>
        Settings
      </Typography>

      <Stack spacing={3}>
        <IntegrationCard
          title="Google Calendar"
          description="Connect your Google account so interviews scheduled for you create a real Calendar event with an invite, instead of relying on a manually pasted meeting link."
          connectLabel="Connect Google Calendar"
          fetchStatus={integrationsApi.googleStatus}
          connect={integrationsApi.connectGoogle}
        />
        {canManageHrIntegration && <HrMailboxSettingsCard />}
        <IntegrationCard
          title="DocuSign"
          description="Connect your DocuSign account so offers you generate are sent as a real e-signature envelope to the candidate, instead of relying on a manually recorded signature."
          connectLabel="Connect DocuSign"
          fetchStatus={integrationsApi.docusignStatus}
          connect={integrationsApi.connectDocusign}
        />
        <IntegrationCard
          title="LinkedIn"
          description="Connect your LinkedIn account so publishing a job with the LinkedIn toggle enabled shares a real hiring announcement to your own feed, instead of asking for a manually pasted posting link. LinkedIn only grants a ~60-day access token with no auto-renewal, so you'll need to reconnect periodically."
          connectLabel="Connect LinkedIn"
          fetchStatus={integrationsApi.linkedinStatus}
          connect={integrationsApi.connectLinkedin}
        />
        <InterviewTrackerSettingsCard />
        <MfaSettingsCard />
        {canManagePlatformSettings && <ConnectionsPanel />}
        {canManagePlatformSettings && <CommunicationsPanel />}
        {canManagePlatformSettings && <AccessControlPanel />}
        {canManagePlatformSettings && <WorkflowsPanel />}
        {canManagePlatformSettings && <MetadataPanel />}
        {canManagePlatformSettings && <CoreHrPanel />}
        {canManagePlatformSettings && <RecruitmentPanel />}
        {canManagePlatformSettings && <OnboardingPanel />}
        {canManagePlatformSettings && <PerformancePanel />}
        {canManagePlatformSettings && <ServiceDeskPanel />}
        {canManagePlatformSettings && <PrivacyPanel />}
        {canManagePlatformSettings && <PlatformSettingsPanel />}
      </Stack>
    </Box>
  );
}
