import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, recruitmentApi, type JobRequisitionRow, type PipelineStageRow, type PipelineTemplateRow } from "../api/client";
import { t as tr } from "../i18n";

// Part 8 (docs/HRMS_COMPLETE_SPEC.txt): configurable pipeline, job requisitions,
// interviewer availability, offer components -- scoped down the same way every other
// part's admin surface has been (plain lists + simple forms). The full Kanban pipeline
// board, drag-drop stage editor, and CTC breakup builder UI are real, tested backend
// capabilities without a frontend yet -- see docs/build_log.md's own Part 8 note.

function PipelineTab() {
  const [templates, setTemplates] = useState<PipelineTemplateRow[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [stages, setStages] = useState<PipelineStageRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    recruitmentApi
      .pipelineTemplates()
      .then((rows) => {
        setTemplates(rows);
        const defaultTemplate = rows.find((t) => t.is_default) || rows[0];
        if (defaultTemplate) setTemplateId(defaultTemplate.id);
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load pipeline templates")));
  };

  useEffect(load, []);

  useEffect(() => {
    if (!templateId) return;
    recruitmentApi
      .pipelineStages(templateId)
      .then(setStages)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load pipeline stages")));
  }, [templateId]);

  const handleSeedDefault = async () => {
    try {
      await recruitmentApi.seedDefaultPipelineTemplate();
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to seed the default pipeline template"));
    }
  };

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      <Stack direction="row" spacing={1} mb={2} alignItems="center">
        <Select size="small" value={templateId} onChange={(e) => setTemplateId(e.target.value)} sx={{ minWidth: 240 }}>
          {templates.map((t) => (
            <MenuItem key={t.id} value={t.id}>
              {t.name} {t.is_default ? "(default)" : ""}
            </MenuItem>
          ))}
        </Select>
        {templates.length === 0 && (
          <Button size="small" variant="contained" onClick={handleSeedDefault}>
            Seed default pipeline
          </Button>
        )}
      </Stack>
      <List dense disablePadding>
        {stages.map((s) => (
          <ListItem key={s.id} divider>
            <ListItemText
              primary={
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography variant="body2">{s.name_i18n.en || s.code}</Typography>
                  <Chip label={s.category} size="small" variant="outlined" />
                </Stack>
              }
              secondary={s.code}
            />
          </ListItem>
        ))}
      </List>
    </Box>
  );
}

function RequisitionsTab() {
  const [requisitions, setRequisitions] = useState<JobRequisitionRow[]>([]);
  const [title, setTitle] = useState("");
  const [headcount, setHeadcount] = useState("1");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    recruitmentApi
      .requisitions()
      .then(setRequisitions)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load requisitions")));
  };

  useEffect(load, []);

  const handleCreate = async () => {
    if (!title) return;
    try {
      await recruitmentApi.createRequisition({ title, headcount: Number(headcount) || 1 });
      setTitle("");
      setHeadcount("1");
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to create requisition"));
    }
  };

  const handleRequestApproval = async (id: string) => {
    try {
      await recruitmentApi.requestRequisitionApproval(id);
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to request approval"));
    }
  };

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      <Stack direction="row" spacing={1} mb={2}>
        <TextField size="small" label="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <TextField size="small" label="Headcount" type="number" value={headcount} onChange={(e) => setHeadcount(e.target.value)} sx={{ width: 120 }} />
        <Button size="small" variant="contained" onClick={handleCreate} disabled={!title}>
          Create requisition
        </Button>
      </Stack>
      <List dense disablePadding>
        {requisitions.map((r) => (
          <ListItem key={r.id} divider secondaryAction={r.status === "draft" && <Button size="small" onClick={() => handleRequestApproval(r.id)}>Request approval</Button>}>
            <ListItemText
              primary={
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography variant="body2">{r.title}</Typography>
                  <Chip label={r.status} size="small" />
                  <Chip label={`x${r.headcount}`} size="small" variant="outlined" />
                </Stack>
              }
            />
          </ListItem>
        ))}
        {requisitions.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            No requisitions yet.
          </Typography>
        )}
      </List>
    </Box>
  );
}

function AvailabilityAndCtcTab() {
  const [interviewerEmail, setInterviewerEmail] = useState("");
  const [interviewerName, setInterviewerName] = useState("");
  const [componentCode, setComponentCode] = useState("");
  const [componentValue, setComponentValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const handleAddAvailability = async () => {
    if (!interviewerEmail) return;
    try {
      await recruitmentApi.upsertInterviewerAvailability({ interviewer_email: interviewerEmail, interviewer_name: interviewerName || undefined });
      setSaved(`Availability saved for ${interviewerEmail}`);
      setInterviewerEmail("");
      setInterviewerName("");
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to save interviewer availability"));
    }
  };

  const handleAddComponent = async () => {
    if (!componentCode || !componentValue) return;
    try {
      await recruitmentApi.createOfferComponent({ code: componentCode, name: componentCode, type: "fixed", value: Number(componentValue) });
      setSaved(`Offer component ${componentCode} added`);
      setComponentCode("");
      setComponentValue("");
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to add offer component"));
    }
  };

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {saved && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaved(null)}>
          {saved}
        </Alert>
      )}
      <Typography variant="subtitle2" mb={1}>
        Interviewer availability (recruitment.negotiation.busy_source = "internal")
      </Typography>
      <Stack direction="row" spacing={1} mb={3}>
        <TextField size="small" label="Interviewer email" value={interviewerEmail} onChange={(e) => setInterviewerEmail(e.target.value)} />
        <TextField size="small" label="Name" value={interviewerName} onChange={(e) => setInterviewerName(e.target.value)} />
        <Button size="small" variant="contained" onClick={handleAddAvailability} disabled={!interviewerEmail}>
          Save
        </Button>
      </Stack>

      <Typography variant="subtitle2" mb={1}>
        Offer CTC components (fixed amount)
      </Typography>
      <Stack direction="row" spacing={1}>
        <TextField size="small" label="Code" value={componentCode} onChange={(e) => setComponentCode(e.target.value)} />
        <TextField size="small" label="Amount" type="number" value={componentValue} onChange={(e) => setComponentValue(e.target.value)} />
        <Button size="small" variant="contained" onClick={handleAddComponent} disabled={!componentCode || !componentValue}>
          Add component
        </Button>
      </Stack>
    </Box>
  );
}

const TABS = ["Pipeline", "Requisitions", "Availability & CTC"] as const;

/** Part 16.3: `only` shows a single tab (one Settings sub-page) without the tab bar. */
export default function RecruitmentPanel({ only }: { only?: (typeof TABS)[number] } = {}) {
  const [tab, setTab] = useState<(typeof TABS)[number]>(only ?? "Pipeline");

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" mb={1}>
          {tr("settings.hiring.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          {tr("settings.hiring.intro")}
        </Typography>
        {!only && (<Tabs value={tab} onChange={(_e, value) => setTab(value)} sx={{ mb: 2 }}>
          {TABS.map((t) => (
            <Tab key={t} label={t} value={t} />
          ))}
        </Tabs>)}
        {tab === "Pipeline" && <PipelineTab />}
        {tab === "Requisitions" && <RequisitionsTab />}
        {tab === "Availability & CTC" && <AvailabilityAndCtcTab />}
      </CardContent>
    </Card>
  );
}
