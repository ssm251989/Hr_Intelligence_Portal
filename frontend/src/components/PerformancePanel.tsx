import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, performanceApi, type CriticalPositionRow, type GoalTreeNode, type ReviewCycleRow } from "../api/client";

// Part 10 (docs/HRMS_COMPLETE_SPEC.txt): review cycles (create -> preview eligibility ->
// launch), the goal alignment tree, and critical-position succession coverage. The
// calibration 9-box drag board, compensation worksheet grid and employee self-service
// pages have complete backend APIs but no screens yet (see docs/build_log.md Part 10).

const CYCLE_TYPES = ["annual", "half_yearly", "quarterly", "probation", "project_end"];
const COVERAGE_COLOR = { covered: "success", at_risk: "warning", uncovered: "error" } as const;

function CyclesTab() {
  const [cycles, setCycles] = useState<ReviewCycleRow[]>([]);
  const [form, setForm] = useState({ name: "", cycle_type: "annual", period_start: "", period_end: "" });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = () => performanceApi.cycles().then(setCycles).catch((err) => setError(extractErrorMessage(err, "Failed to load cycles")));
  useEffect(() => {
    load();
  }, []);

  const create = () => {
    performanceApi
      .createCycle({
        ...form,
        stages: [
          { stage: "self", weight: 20 },
          { stage: "manager", weight: 80 },
        ],
        sections: [
          { key: "goals", weight: 70 },
          { key: "competencies", weight: 30 },
        ],
      })
      .then(() => {
        setNotice("Cycle created as a draft. Preview eligibility before launching.");
        load();
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to create cycle")));
  };

  const preview = (row: ReviewCycleRow) =>
    performanceApi.eligibilityPreview(row.id).then((r) => setNotice(`${r.eligible_count} employees are eligible for ${row.name}.`));

  const launch = (row: ReviewCycleRow) =>
    performanceApi
      .launchCycle(row.id)
      .then((r) => {
        setNotice(`Launched: ${r.reviews_created} reviews created for ${r.eligible} employees.`);
        load();
      })
      .catch((err) => setError(extractErrorMessage(err, "Launch failed")));

  return (
    <Box>
      {error && <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>{error}</Alert>}
      {notice && <Alert severity="info" onClose={() => setNotice(null)} sx={{ mb: 2 }}>{notice}</Alert>}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 2 }}>
        <TextField size="small" label="Cycle name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <TextField size="small" select label="Type" value={form.cycle_type} onChange={(e) => setForm({ ...form, cycle_type: e.target.value })} sx={{ minWidth: 140 }}>
          {CYCLE_TYPES.map((t) => (
            <MenuItem key={t} value={t}>{t.replace("_", " ")}</MenuItem>
          ))}
        </TextField>
        <TextField size="small" type="date" label="From" InputLabelProps={{ shrink: true }} value={form.period_start} onChange={(e) => setForm({ ...form, period_start: e.target.value })} />
        <TextField size="small" type="date" label="To" InputLabelProps={{ shrink: true }} value={form.period_end} onChange={(e) => setForm({ ...form, period_end: e.target.value })} />
        <Button variant="contained" onClick={create} disabled={!form.name || !form.period_start || !form.period_end}>Create</Button>
      </Stack>
      {cycles.length === 0 ? (
        <Typography color="text.secondary">No review cycles yet. Create one above; it stays a draft until you launch it.</Typography>
      ) : (
        <List dense>
          {cycles.map((row) => (
            <ListItem
              key={row.id}
              secondaryAction={
                row.status === "draft" ? (
                  <Box>
                    <Button size="small" onClick={() => preview(row)}>Preview</Button>
                    <Button size="small" variant="outlined" onClick={() => launch(row)}>Launch</Button>
                  </Box>
                ) : null
              }
            >
              <ListItemText primary={row.name} secondary={`${row.cycle_type} · ${row.period_start} → ${row.period_end} · ${row.status}`} />
            </ListItem>
          ))}
        </List>
      )}
    </Box>
  );
}

function GoalNode({ node, depth }: { node: GoalTreeNode; depth: number }) {
  const progress = node.rolled_up_progress_pct ?? node.progress_pct;
  return (
    <Box sx={{ pl: depth * 2, py: 0.5 }}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Chip size="small" label={node.level} />
        <Typography variant="body2" sx={{ flex: 1 }}>{node.title}</Typography>
        <Typography variant="caption">{Math.round(progress)}%</Typography>
      </Stack>
      <LinearProgress variant="determinate" value={Math.min(100, progress)} sx={{ mt: 0.5 }} aria-label={`${node.title} progress`} />
      {node.children.map((child) => (
        <GoalNode key={child.id} node={child} depth={depth + 1} />
      ))}
    </Box>
  );
}

function GoalsTab() {
  const [tree, setTree] = useState<GoalTreeNode[]>([]);
  useEffect(() => {
    performanceApi.goalTree().then(setTree).catch(() => undefined);
  }, []);
  return tree.length === 0 ? (
    <Typography color="text.secondary">No goals yet. Company goals created via the API cascade down to departments, teams and people.</Typography>
  ) : (
    <Box>{tree.map((node) => <GoalNode key={node.id} node={node} depth={0} />)}</Box>
  );
}

function SuccessionTab() {
  const [rows, setRows] = useState<CriticalPositionRow[]>([]);
  useEffect(() => {
    performanceApi.criticalPositions().then(setRows).catch(() => undefined);
  }, []);
  return rows.length === 0 ? (
    <Typography color="text.secondary">No critical positions. Mark a position as critical in Core HR to track its successors here.</Typography>
  ) : (
    <List dense>
      {rows.map((row) => (
        <ListItem key={row.position_id}>
          <ListItemText primary={row.title} secondary={`${row.successors.length} successor(s)`} />
          <Chip size="small" color={COVERAGE_COLOR[row.coverage]} label={row.coverage.replace("_", " ")} />
        </ListItem>
      ))}
    </List>
  );
}

export default function PerformancePanel() {
  const [tab, setTab] = useState(0);
  return (
    <Card sx={{ mt: 3 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>Performance & talent</Typography>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
          <Tab label="Review cycles" />
          <Tab label="Goals" />
          <Tab label="Succession" />
        </Tabs>
        {tab === 0 && <CyclesTab />}
        {tab === 1 && <GoalsTab />}
        {tab === 2 && <SuccessionTab />}
      </CardContent>
    </Card>
  );
}
