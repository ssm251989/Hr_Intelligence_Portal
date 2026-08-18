import { useState } from "react";
import PersonAddAltOutlinedIcon from "@mui/icons-material/PersonAddAltOutlined";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { Link as RouterLink } from "react-router-dom";

import CandidatesDashboardStats from "../components/CandidatesDashboardStats";
import LastImportRunCard from "../components/LastImportRunCard";
import ScreeningThresholdPanel from "../components/ScreeningThresholdPanel";
import UploadCandidateDialog from "../components/UploadCandidateDialog";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";

export default function CandidatesDashboardPage() {
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.candidatesWrite);
  const [addOpen, setAddOpen] = useState(false);
  // Bumped whenever the "Add Candidate" dialog links a new candidate to a job, so the
  // stats below (which own their own data fetch) refetch without a full page reload.
  const [refreshSignal, setRefreshSignal] = useState(0);

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" mb={3} flexWrap="wrap" gap={2}>
        <Box>
          <Typography variant="h4">Candidates Dashboard</Typography>
          <Typography variant="body2" color="text.secondary">
            Overview of all candidates and data
          </Typography>
        </Box>
        <Stack direction="row" spacing={2}>
          <Button variant="outlined" startIcon={<UploadFileOutlinedIcon />} component={RouterLink} to="/candidates/import">
            Import Candidates
          </Button>
          {canWrite && (
            <Button variant="contained" startIcon={<PersonAddAltOutlinedIcon />} onClick={() => setAddOpen(true)}>
              Add Candidate
            </Button>
          )}
        </Stack>
      </Stack>

      <ScreeningThresholdPanel />

      <LastImportRunCard />

      <CandidatesDashboardStats refreshSignal={refreshSignal} />

      <UploadCandidateDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onLinked={() => setRefreshSignal((s) => s + 1)}
      />
    </Box>
  );
}
