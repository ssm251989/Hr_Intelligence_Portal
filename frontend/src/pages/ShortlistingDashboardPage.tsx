import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import { Link as RouterLink } from "react-router-dom";

import RefreshButton from "../components/RefreshButton";
import ShortlistingDashboardStats from "../components/ShortlistingDashboardStats";
import { useT } from "../i18n";
import { PageHeader } from "../ui-kit";

export default function ShortlistingDashboardPage() {
  const t = useT();
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  return (
    <Box>
      <PageHeader
        emoji="star"
        title={t("shortlisting.dashboard.title")}
        purpose={t("shortlisting.dashboard.purpose")}
        tourKey="shortlisting"
        primary={
          <Button variant="contained" component={RouterLink} to="/shortlisting/list?shortlist_status=under_review">
            {t("shortlisting.dashboard.primary")}
          </Button>
        }
        extra={<RefreshButton loading={refreshing} onRefresh={() => setRefreshSignal((s) => s + 1)} label={t("screening.refresh")} />}
      />

      <ShortlistingDashboardStats refreshSignal={refreshSignal} onLoadingChange={setRefreshing} />
    </Box>
  );
}
