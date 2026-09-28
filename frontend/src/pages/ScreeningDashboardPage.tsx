import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import { Link as RouterLink } from "react-router-dom";

import RefreshButton from "../components/RefreshButton";
import ScreeningDashboardStats from "../components/ScreeningDashboardStats";
import ScoringRulesLink from "../components/scoring/ScoringRulesLink";
import { useT } from "../i18n";
import { PageHeader } from "../ui-kit";

// Part 17.4: the ONE company "Shortlist threshold" (plus "Check everyone again") lives
// here only -- the Candidates Dashboard no longer has its own threshold panel.
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

      {/* Part 18.10: the shortlist score is edited only in Settings > Hiring > Scoring rules */}
      <ScoringRulesLink />

      <ScreeningDashboardStats refreshSignal={refreshSignal} onLoadingChange={setRefreshing} />
    </Box>
  );
}
