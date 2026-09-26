import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import { Link as RouterLink, useNavigate } from "react-router-dom";

import ImportCandidatesWizard from "../components/ImportCandidatesWizard";
import { useT } from "../i18n";
import { PageHeader } from "../ui-kit";

// Hosts the same ImportCandidatesWizard used before -- now shown in place on the page in
// the step-form look (Part 15.4) instead of as a dialog. Closing it (Cancel/Done) sends the
// recruiter to the List so they can see what just came in.
export default function CandidatesImportPage() {
  const navigate = useNavigate();
  const t = useT();

  return (
    <Box>
      <PageHeader
        emoji="technologist"
        title={t("candidates.import.title")}
        purpose={t("candidates.import.purpose")}
        tourKey="candidates"
        primary={
          <Button variant="outlined" component={RouterLink} to="/candidates/list">
            {t("candidates.import.see_list")}
          </Button>
        }
      />
      <ImportCandidatesWizard
        open
        variant="page"
        onClose={() => navigate("/candidates/list")}
        onImported={() => {}}
        initialSource={null}
      />
    </Box>
  );
}
