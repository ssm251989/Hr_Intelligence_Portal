import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import ShortlistingDashboardStats from "../components/ShortlistingDashboardStats";

export default function ShortlistingDashboardPage() {
  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" mb={3} flexWrap="wrap" gap={2}>
        <Box>
          <Typography variant="h4">Shortlisting Dashboard</Typography>
          <Typography variant="body2" color="text.secondary">
            Overview of shortlisting decisions across every screened application
          </Typography>
        </Box>
      </Stack>

      <ShortlistingDashboardStats />
    </Box>
  );
}
