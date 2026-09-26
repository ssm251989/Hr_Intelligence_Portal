import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
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

import { extractErrorMessage, metadataApi, type CustomFieldDefRow, type MasterTypeRow, type MasterValueRow } from "../api/client";
import { t as tr } from "../i18n";

// Part 6 (docs/HRMS_COMPLETE_SPEC.txt sections 1-4's UI, scoped down the same way every
// other part's admin surface has been): plain lists + simple create forms for custom
// field defs and master values, a sequence preview/advance tool. Deliberately NOT the
// spec's full drag-drop form builder or a rich picklist hierarchy editor -- see
// docs/build_log.md's own Part 6 note.

const EXTENSIBLE_ENTITIES = ["employee", "candidate", "job", "application", "requisition", "asset", "ticket", "separation"];
const FIELD_TYPES = ["text", "longtext", "number", "decimal", "date", "datetime", "bool", "picklist", "multipicklist", "email", "phone", "url"];

function CustomFieldsTab() {
  const [entity, setEntity] = useState("candidate");
  const [defs, setDefs] = useState<CustomFieldDefRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [type, setType] = useState("text");

  const load = () => {
    setLoading(true);
    metadataApi
      .customFields(entity)
      .then(setDefs)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load custom fields")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [entity]);

  const handleCreate = async () => {
    if (!code) return;
    try {
      await metadataApi.createCustomField({ entity, code, type, label_i18n: { en: code } });
      setCode("");
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to create custom field"));
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await metadataApi.deleteCustomField(id);
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to delete custom field"));
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
        <Select size="small" value={entity} onChange={(e) => setEntity(e.target.value)}>
          {EXTENSIBLE_ENTITIES.map((e) => (
            <MenuItem key={e} value={e}>
              {e}
            </MenuItem>
          ))}
        </Select>
        <TextField size="small" label="Field code" value={code} onChange={(e) => setCode(e.target.value)} />
        <Select size="small" value={type} onChange={(e) => setType(e.target.value)}>
          {FIELD_TYPES.map((t) => (
            <MenuItem key={t} value={t}>
              {t}
            </MenuItem>
          ))}
        </Select>
        <Button size="small" variant="contained" onClick={handleCreate} disabled={!code}>
          Add field
        </Button>
      </Stack>
      {loading ? (
        <CircularProgress size={24} />
      ) : (
        <List dense disablePadding>
          {defs.map((d) => (
            <ListItem key={d.id} divider secondaryAction={<Button size="small" onClick={() => handleDelete(d.id)}>Delete</Button>}>
              <ListItemText
                primary={
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="body2">{d.code}</Typography>
                    <Chip label={d.type} size="small" variant="outlined" />
                    {d.sensitive && <Chip label="sensitive" size="small" color="warning" />}
                  </Stack>
                }
                secondary={d.section || undefined}
              />
            </ListItem>
          ))}
          {defs.length === 0 && (
            <Typography variant="body2" color="text.secondary">
              No custom fields for {entity} yet.
            </Typography>
          )}
        </List>
      )}
    </Box>
  );
}

function MastersTab() {
  const [types, setTypes] = useState<MasterTypeRow[]>([]);
  const [typeCode, setTypeCode] = useState("");
  const [values, setValues] = useState<MasterValueRow[]>([]);
  const [newCode, setNewCode] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    metadataApi
      .masterTypes()
      .then((t) => {
        setTypes(t);
        if (t.length > 0) setTypeCode(t[0].code);
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load master types")));
  }, []);

  const loadValues = (code: string) => {
    metadataApi
      .masterValues(code)
      .then(setValues)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load master values")));
  };

  useEffect(() => {
    if (typeCode) loadValues(typeCode);
  }, [typeCode]);

  const handleCreate = async () => {
    if (!newCode || !typeCode) return;
    try {
      await metadataApi.createMasterValue(typeCode, { code: newCode, label_i18n: { en: newLabel || newCode } });
      setNewCode("");
      setNewLabel("");
      loadValues(typeCode);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to add value"));
    }
  };

  const handleDeactivate = async (id: string) => {
    try {
      await metadataApi.deactivateMasterValue(id);
      loadValues(typeCode);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to deactivate value"));
    }
  };

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      <Select size="small" value={typeCode} onChange={(e) => setTypeCode(e.target.value)} sx={{ mb: 2, minWidth: 220 }}>
        {types.map((t) => (
          <MenuItem key={t.code} value={t.code}>
            {t.name}
          </MenuItem>
        ))}
      </Select>
      <Stack direction="row" spacing={1} mb={2}>
        <TextField size="small" label="Code" value={newCode} onChange={(e) => setNewCode(e.target.value)} />
        <TextField size="small" label="Label" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} />
        <Button size="small" variant="contained" onClick={handleCreate} disabled={!newCode}>
          Add value
        </Button>
      </Stack>
      <List dense disablePadding>
        {values.map((v) => (
          <ListItem key={v.id} divider secondaryAction={<Button size="small" onClick={() => handleDeactivate(v.id)}>Deactivate</Button>}>
            <ListItemText primary={v.label_i18n.en || v.code} secondary={v.code} />
          </ListItem>
        ))}
      </List>
    </Box>
  );
}

function SequencesTab() {
  const [key, setKey] = useState("");
  const [pattern, setPattern] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleDefine = async () => {
    if (!key || !pattern) return;
    try {
      await metadataApi.defineSequence({ key, pattern });
      setError(null);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to define sequence"));
    }
  };

  const handleAdvance = async () => {
    if (!key) return;
    try {
      const { value } = await metadataApi.nextSequenceValue(key);
      setResult(value);
      setError(null);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to advance sequence"));
    }
  };

  return (
    <Box>
      <Typography variant="body2" color="text.secondary" mb={2}>
        Numbering sequences (e.g. employee_code, offer_no, ticket_no) -- pattern example:{" "}
        <code>OFR-{"{YYYY}"}-{"{SEQ:5}"}</code>
      </Typography>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      <Stack direction="row" spacing={1} mb={2}>
        <TextField size="small" label="Key" value={key} onChange={(e) => setKey(e.target.value)} />
        <TextField size="small" label="Pattern" value={pattern} onChange={(e) => setPattern(e.target.value)} sx={{ minWidth: 220 }} />
        <Button size="small" variant="contained" onClick={handleDefine} disabled={!key || !pattern}>
          Define
        </Button>
        <Button size="small" onClick={handleAdvance} disabled={!key}>
          Get next value
        </Button>
      </Stack>
      {result && <Chip label={result} color="success" />}
    </Box>
  );
}

const TABS = ["Custom Fields", "Masters", "Sequences"] as const;

/** Part 16.3: `only` shows a single tab (one Settings sub-page) without the tab bar. */
export default function MetadataPanel({ only }: { only?: (typeof TABS)[number] } = {}) {
  const [tab, setTab] = useState<(typeof TABS)[number]>(only ?? "Custom Fields");

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" mb={1}>
          {tr("settings.metadata.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          {tr("settings.metadata.intro")}
        </Typography>
        {!only && (<Tabs value={tab} onChange={(_e, value) => setTab(value)} sx={{ mb: 2 }}>
          {TABS.map((t) => (
            <Tab key={t} label={t} value={t} />
          ))}
        </Tabs>)}
        {tab === "Custom Fields" && <CustomFieldsTab />}
        {tab === "Masters" && <MastersTab />}
        {tab === "Sequences" && <SequencesTab />}
      </CardContent>
    </Card>
  );
}
