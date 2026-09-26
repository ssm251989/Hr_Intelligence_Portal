import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import { Link as RouterLink } from "react-router-dom";

import InterviewReadinessThresholdPanel from "../components/InterviewReadinessThresholdPanel";
import RefreshButton from "../components/RefreshButton";
import ScreeningDashboardStats from "../components/ScreeningDashboardStats";
import { useT } from "../i18n";
import { PageHeader } from "../ui-kit";

// Part D's dashboard_min/max_score threshold + Re-evaluate All action lives on the
// Candidates Dashboard, not here -- deliberately not duplicated onto this page. Part F's
// own, separate interview_min/max_score threshold DOES live here (InterviewReadinessThreshold
// Panel below), since it is "the Screening module's own" threshold.
export default function ScreeningDashboardPage() {
  const t = useT();
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  return (
    <Box>
      <PageHeader
        emoji="magnifier"
        title={t("screening.dashboard.title")}
        purpose={t("screening.dashboard.purpose")}
        tourKey="screening"
        primary={
          <Button variant="contained" component={RouterLink} to="/screening/list">
            {t("screening.dashboard.primary")}
          </Button>
        }
        extra={<RefreshButton loading={refreshing} onRefresh={() => setRefreshSignal((s) => s + 1)} label={t("screening.refresh")} />}
      />

      <InterviewReadinessThresholdPanel refreshSignal={refreshSignal} />

      <ScreeningDashboardStats refreshSignal={refreshSignal} onLoadingChange={setRefreshing} />
    </Box>
  );
}
