import { useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, intelligenceApi, type DatasetRead, type ReportDefinition, type ReportResult } from "../api/client";

// Part 12 section A (docs/HRMS_COMPLETE_SPEC.txt): a working report builder -- dataset ->
// columns -> optional group-by with a count -> run -> save. Every run is server-side and
// permission-scoped (a manager only ever gets their reportees). The drag-and-drop canvas,
// pivot/chart editor and schedule dialog are backend-complete but not built as UI here.

export default function AnalyticsPanel() {
  const [datasets, setDatasets] = useState<DatasetRead[]>([]);
  const [datasetCode, setDatasetCode] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [groupBy, setGroupBy] = useState("");
  const [result, setResult] = useState<ReportResult | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    intelligenceApi
      .datasets()
      .then((rows) => {
        setDatasets(rows);
        if (rows[0]) setDatasetCode(rows[0].code);
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load datasets")));
  }, []);

  const dataset = useMemo(() => datasets.find((d) => d.code === datasetCode), [datasets, datasetCode]);

  useEffect(() => {
    setColumns(dataset ? dataset.fields.slice(0, 4).map((f) => f.key) : []);
    setGroupBy("");
    setResult(null);
  }, [dataset]);

  const definition = (): ReportDefinition =>
    groupBy ? { group_by: [groupBy], measures: [{ field: "*", agg: "count", as: "count" }], sort: [{ field: "count", dir: "desc" }] } : { columns, limit: 200 };

  const run = () => {
    setError(null);
    intelligenceApi
      .runReport(datasetCode, definition())
      .then(setResult)
      .catch((err) => setError(extractErrorMessage(err, "Report failed")));
  };

  const save = () =>
    intelligenceApi
      .saveReport({ name, dataset: datasetCode, definition: definition() })
      .then(() => setNotice(`Saved "${name}". Open Reports to export or schedule it.`))
      .catch((err) => setError(extractErrorMessage(err, "Save failed")));

  if (datasets.length === 0 && !error) {
    return null; // no dataset permissions -> nothing to build
  }

  return (
    <Card sx={{ mt: 3 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>Report builder</Typography>
        {error && <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>{error}</Alert>}
        {notice && <Alert severity="success" onClose={() => setNotice(null)} sx={{ mb: 2 }}>{notice}</Alert>}
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 2 }}>
          <TextField select size="small" label="Dataset" value={datasetCode} onChange={(e) => setDatasetCode(e.target.value)} sx={{ minWidth: 200 }}>
            {datasets.map((d) => (
              <MenuItem key={d.code} value={d.code}>{d.label}</MenuItem>
            ))}
          </TextField>
          <TextField select size="small" label="Group by (count)" value={groupBy} onChange={(e) => setGroupBy(e.target.value)} sx={{ minWidth: 200 }}>
            <MenuItem value="">No grouping</MenuItem>
            {dataset?.fields.map((f) => (
              <MenuItem key={f.key} value={f.key}>{f.label}</MenuItem>
            ))}
          </TextField>
          <Button variant="contained" onClick={run} disabled={!datasetCode}>Run</Button>
        </Stack>
        {!groupBy && dataset && (
          <Box sx={{ mb: 2 }}>
            {dataset.fields.map((f) => (
              <FormControlLabel
                key={f.key}
                control={
                  <Checkbox size="small" checked={columns.includes(f.key)}
                    onChange={(e) => setColumns((prev) => (e.target.checked ? [...prev, f.key] : prev.filter((c) => c !== f.key)))} />
                }
                label={f.label}
              />
            ))}
          </Box>
        )}
        {result && (
          <>
            <Typography variant="caption" color="text.secondary">{result.total} row(s){result.total > result.rows.length ? `, showing ${result.rows.length}` : ""}</Typography>
            {result.rows.length === 0 ? (
              <Typography color="text.secondary" sx={{ mt: 1 }}>No rows match. Widen the filters, or check you have access to this data.</Typography>
            ) : (
              <Box sx={{ overflowX: "auto", mt: 1 }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>{result.columns.map((c) => <TableCell key={c}>{c}</TableCell>)}</TableRow>
                  </TableHead>
                  <TableBody>
                    {result.rows.map((row, i) => (
                      <TableRow key={i}>{result.columns.map((c) => <TableCell key={c}>{String(row[c] ?? "")}</TableCell>)}</TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}
            <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
              <TextField size="small" label="Report name" value={name} onChange={(e) => setName(e.target.value)} />
              <Button onClick={save} disabled={!name.trim()}>Save report</Button>
            </Stack>
          </>
        )}
      </CardContent>
    </Card>
  );
}
