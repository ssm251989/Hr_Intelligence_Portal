import { useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import RefreshButton from "../components/RefreshButton";
import ShortlistingDashboardStats from "../components/ShortlistingDashboardStats";

export default function ShortlistingDashboardPage() {
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" mb={3} flexWrap="wrap" gap={2}>
        <Box>
          <Typography variant="h4">Shortlisting Dashboard</Typography>
          <Typography variant="body2" color="text.secondary">
            Overview of shortlisting decisions across every screened application
          </Typography>
        </Box>
        <RefreshButton loading={refreshing} onRefresh={() => setRefreshSignal((s) => s + 1)} />
      </Stack>

      <ShortlistingDashboardStats refreshSignal={refreshSignal} onLoadingChange={setRefreshing} />
    </Box>
  );
}
