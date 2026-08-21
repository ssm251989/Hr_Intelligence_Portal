import { useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import InterviewReadinessThresholdPanel from "../components/InterviewReadinessThresholdPanel";
import RefreshButton from "../components/RefreshButton";
import ScreeningDashboardStats from "../components/ScreeningDashboardStats";

// Part D's dashboard_min/max_score threshold + Re-evaluate All action lives on the
// Candidates Dashboard, not here -- deliberately not duplicated onto this page. Part F's
// own, separate interview_min/max_score threshold DOES live here (InterviewReadinessThreshold
// Panel below), since the docstring on app/models/screening_settings.py frames it as "the
// Screening module's own" threshold, as opposed to Part D's Candidates-Dashboard-owned one.
export default function ScreeningDashboardPage() {
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" mb={3} flexWrap="wrap" gap={2}>
        <Box>
          <Typography variant="h4">Screening Dashboard</Typography>
          <Typography variant="body2" color="text.secondary">
            Overview of AI screening across every application
          </Typography>
        </Box>
        <RefreshButton loading={refreshing} onRefresh={() => setRefreshSignal((s) => s + 1)} />
      </Stack>

      <InterviewReadinessThresholdPanel />

      <ScreeningDashboardStats refreshSignal={refreshSignal} onLoadingChange={setRefreshing} />
    </Box>
  );
}
