import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import { Link as RouterLink } from "react-router-dom";

import InterviewsDashboardStats from "../components/InterviewsDashboardStats";
import RefreshButton from "../components/RefreshButton";
import { useT } from "../i18n";
import Emoji from "../ui-kit/Emoji";
import PageHeader from "../ui-kit/PageHeader";

export default function InterviewsDashboardPage() {
  const t = useT();
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  return (
    <Box>
      <PageHeader
        emoji="calendar"
        title={t("interviews.dash.title")}
        purpose={t("interviews.dash.purpose")}
        tourKey="interviews"
        extra={<RefreshButton loading={refreshing} onRefresh={() => setRefreshSignal((s) => s + 1)} />}
        primary={
          <Button variant="contained" component={RouterLink} to="/interviews/list?view=week" startIcon={<Emoji name="calendar" size={18} />}>
            {t("interviews.dash.open_week")}
          </Button>
        }
      />

      <InterviewsDashboardStats refreshSignal={refreshSignal} onLoadingChange={setRefreshing} />
    </Box>
  );
}
