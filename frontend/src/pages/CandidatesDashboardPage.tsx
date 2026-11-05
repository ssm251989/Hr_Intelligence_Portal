import { useState } from "react";
import PersonAddAltOutlinedIcon from "@mui/icons-material/PersonAddAltOutlined";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import { Link as RouterLink } from "react-router-dom";

import CandidatesDashboardStats from "../components/CandidatesDashboardStats";
import RefreshButton from "../components/RefreshButton";
import UploadCandidateDialog from "../components/UploadCandidateDialog";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { useT } from "../i18n";
import { PageHeader } from "../ui-kit";

// Part 15.4: Candidates dashboard in the new look -- PageHeader with ONE main button
// ("Add a candidate" for people who may add them, otherwise "Import candidates"), stat
// tiles and themed charts below. Same data, dialogs and permissions as before.
export default function CandidatesDashboardPage() {
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.candidatesWrite);
  const t = useT();
  const [addOpen, setAddOpen] = useState(false);
  // Bumped whenever the "Add Candidate" dialog links a new candidate to a job, or the
  // Refresh button is clicked, so the stats below (which own their own data fetch) refetch
  // without a full page reload.
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const importButton = (variant: "contained" | "outlined") => (
    <Button variant={variant} startIcon={<UploadFileOutlinedIcon />} component={RouterLink} to="/candidates/import">
      {t("candidates.import_button")}
    </Button>
  );

  return (
    <Box>
      <PageHeader
        emoji="technologist"
        title={t("candidates.dash.title")}
        purpose={t("candidates.dash.purpose")}
        tourKey="candidates"
        primary={
          canWrite ? (
            <Button variant="contained" startIcon={<PersonAddAltOutlinedIcon />} onClick={() => setAddOpen(true)}>
              {t("candidates.add_button")}
            </Button>
          ) : (
            importButton("contained")
          )
        }
        extra={
          <>
            {canWrite && importButton("outlined")}
            <RefreshButton loading={refreshing} onRefresh={() => setRefreshSignal((s) => s + 1)} />
          </>
        }
      />

      <CandidatesDashboardStats refreshSignal={refreshSignal} onLoadingChange={setRefreshing} />

      <UploadCandidateDialog open={addOpen} onClose={() => setAddOpen(false)} onLinked={() => setRefreshSignal((s) => s + 1)} />
    </Box>
  );
}
