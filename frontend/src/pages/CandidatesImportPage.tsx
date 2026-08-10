import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { useNavigate } from "react-router-dom";

import ImportCandidatesWizard from "../components/ImportCandidatesWizard";

// Hosts the same ImportCandidatesWizard used before -- now reached directly from the
// sidebar rather than opened as a dialog from the List page. Closing it (Cancel/Done)
// sends the recruiter to the List so they can see what just came in.
export default function CandidatesImportPage() {
  const navigate = useNavigate();

  return (
    <Box>
      <Typography variant="h4" mb={3}>
        Import from Source
      </Typography>
      <ImportCandidatesWizard
        open
        onClose={() => navigate("/candidates/list")}
        onImported={() => {}}
        initialSource={null}
      />
    </Box>
  );
}
