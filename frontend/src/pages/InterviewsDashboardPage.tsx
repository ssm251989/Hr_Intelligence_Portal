import { useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import InterviewsDashboardStats from "../components/InterviewsDashboardStats";
import RefreshButton from "../components/RefreshButton";

export default function InterviewsDashboardPage() {
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" mb={3} flexWrap="wrap" gap={2}>
        <Box>
          <Typography variant="h4">Interview Dashboard</Typography>
          <Typography variant="body2" color="text.secondary">
            Overview of interview scheduling and outcomes across every job
          </Typography>
        </Box>
        <RefreshButton loading={refreshing} onRefresh={() => setRefreshSignal((s) => s + 1)} />
      </Stack>

      <InterviewsDashboardStats refreshSignal={refreshSignal} onLoadingChange={setRefreshing} />
    </Box>
  );
}
