import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import ScreeningDashboardStats from "../components/ScreeningDashboardStats";

// The auto-advance threshold + Re-evaluate All action (Part D) lives on the Candidates
// Dashboard, not here -- deliberately not duplicated onto this page too. This dashboard is
// Part E's read-only overview of what screening has already concluded across every
// application; the screen/rank action buttons live on the Screening List page instead.
export default function ScreeningDashboardPage() {
  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" mb={3} flexWrap="wrap" gap={2}>
        <Box>
          <Typography variant="h4">Screening Dashboard</Typography>
          <Typography variant="body2" color="text.secondary">
            Overview of AI screening across every application
          </Typography>
        </Box>
      </Stack>

      <ScreeningDashboardStats />
    </Box>
  );
}
