import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, workflowApi, type WorkflowDefinitionRow } from "../api/client";
import { t as tr } from "../i18n";

// Part 5B (docs/HRMS_COMPLETE_SPEC.txt section 4's UI, scoped down the same way every
// other part's admin surface has been): a read-only definitions list with a "simulate"
// dry-run dialog. Deliberately NOT the spec's full React Flow drag-drop visual builder --
// a definition's graph_json is authored as data (hrctl.seed_workflows, or the
// POST /api/v1/workflow/definitions API directly), not drawn here. See docs/build_log.md's
// own Part 5 note.

function SimulateDialog({ open, onClose, definition }: { open: boolean; onClose: () => void; definition: WorkflowDefinitionRow | null }) {
  const [sampleJson, setSampleJson] = useState("{}");
  const [result, setResult] = useState<{ node_id: string; type: string }[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setResult(null);
    setError(null);
    setSampleJson("{}");
  }, [definition]);

  const handleRun = async () => {
    if (!definition) return;
    setError(null);
    try {
      const parsed = JSON.parse(sampleJson);
      const { path } = await workflowApi.simulate(definition.id, parsed);
      setResult(path);
    } catch (err) {
      setError(err instanceof SyntaxError ? "Sample context must be valid JSON" : extractErrorMessage(err, "Simulation failed"));
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Simulate: {definition?.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          <Typography variant="body2" color="text.secondary">
            {tr("settings.approvals.test")}
          </Typography>
          <textarea
            value={sampleJson}
            onChange={(e) => setSampleJson(e.target.value)}
            rows={4}
            style={{ fontFamily: "monospace", fontSize: 13, padding: 8 }}
          />
          {error && <Alert severity="error">{error}</Alert>}
          {result && (
            <Box>
              <Typography variant="subtitle2" mb={1}>
                Path taken:
              </Typography>
              <Stack spacing={0.5}>
                {result.map((step, i) => (
                  <Chip key={i} label={`${step.node_id} (${step.type})`} size="small" sx={{ alignSelf: "flex-start" }} />
                ))}
              </Stack>
            </Box>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
        <Button variant="contained" onClick={handleRun}>
          Run
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default function WorkflowsPanel() {
  const [definitionsList, setDefinitionsList] = useState<WorkflowDefinitionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [simulating, setSimulating] = useState<WorkflowDefinitionRow | null>(null);

  useEffect(() => {
    workflowApi
      .definitions()
      .then(setDefinitionsList)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load workflows")))
      .finally(() => setLoading(false));
  }, []);

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" mb={1}>
          {tr("settings.approvals.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          {tr("settings.approvals.intro")}
        </Typography>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        {loading ? (
          <CircularProgress size={24} />
        ) : definitionsList.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No workflows defined yet.
          </Typography>
        ) : (
          <List dense disablePadding>
            {definitionsList.map((d) => (
              <ListItem key={d.id} divider secondaryAction={<Button size="small" onClick={() => setSimulating(d)}>Simulate</Button>}>
                <ListItemText
                  primary={
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Typography variant="body2">{d.name}</Typography>
                      <Chip label={`v${d.version}`} size="small" variant="outlined" />
                      <Chip label={d.status} size="small" color={d.status === "published" ? "success" : "default"} />
                    </Stack>
                  }
                  secondary={d.key}
                />
              </ListItem>
            ))}
          </List>
        )}
        <SimulateDialog open={simulating !== null} onClose={() => setSimulating(null)} definition={simulating} />
      </CardContent>
    </Card>
  );
}
