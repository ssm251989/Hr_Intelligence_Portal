import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";

import CandidatesDashboardStats from "../components/CandidatesDashboardStats";

export default function CandidatesDashboardPage() {
  return (
    <Box>
      <Typography variant="h4" mb={3}>
        Candidates Dashboard
      </Typography>
      <CandidatesDashboardStats />
    </Box>
  );
}
