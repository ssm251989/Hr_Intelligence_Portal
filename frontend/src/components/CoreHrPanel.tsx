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

import { coreHrApi, extractErrorMessage, type DepartmentRow, type EmployeeRow, type PositionRow } from "../api/client";
import { t as tr } from "../i18n";

// Part 7 (docs/HRMS_COMPLETE_SPEC.txt): org model + employee master, scoped down the same
// way every other part's admin surface has been -- plain lists + simple create forms, a
// masked-reveal control for encrypted PII. Deliberately NOT the spec's own drag-drop org
// builder, full ESS/MSS self-service pages, or letter/import wizard UI -- see
// docs/build_log.md's own Part 7 note.

const ENCRYPTED_FIELDS = ["pan", "aadhaar", "passport", "bank_account"] as const;

function EmployeesTab() {
  const [employees, setEmployees] = useState<EmployeeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [revealField, setRevealField] = useState<Record<string, string>>({});
  const [revealTarget, setRevealTarget] = useState<Record<string, (typeof ENCRYPTED_FIELDS)[number]>>({});

  const load = () => {
    setLoading(true);
    coreHrApi
      .employees()
      .then(setEmployees)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load employees")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleCreate = async () => {
    if (!firstName) return;
    try {
      await coreHrApi.createEmployee({ first_name: firstName, last_name: lastName || undefined });
      setFirstName("");
      setLastName("");
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to create employee"));
    }
  };

  const handleReveal = async (employeeId: string) => {
    const field = revealTarget[employeeId] || "pan";
    try {
      const { value } = await coreHrApi.revealEncryptedField(employeeId, field);
      setRevealField((prev) => ({ ...prev, [employeeId]: value || "(not set)" }));
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to reveal field"));
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
        <TextField size="small" label="First name" value={firstName} onChange={(e) => setFirstName(e.target.value)} />
        <TextField size="small" label="Last name" value={lastName} onChange={(e) => setLastName(e.target.value)} />
        <Button size="small" variant="contained" onClick={handleCreate} disabled={!firstName}>
          Add employee
        </Button>
      </Stack>
      {loading ? (
        <CircularProgress size={24} />
      ) : (
        <List dense disablePadding>
          {employees.map((e) => (
            <ListItem key={e.id} divider alignItems="flex-start">
              <ListItemText
                primary={
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="body2">
                      {e.first_name} {e.last_name || ""}
                    </Typography>
                    <Chip label={e.employee_code} size="small" variant="outlined" />
                    <Chip label={e.status} size="small" />
                  </Stack>
                }
                secondary={
                  <Stack direction="row" spacing={1} alignItems="center" mt={0.5}>
                    <Select size="small" value={revealTarget[e.id] || "pan"} onChange={(ev) => setRevealTarget((prev) => ({ ...prev, [e.id]: ev.target.value as (typeof ENCRYPTED_FIELDS)[number] }))}>
                      {ENCRYPTED_FIELDS.map((f) => (
                        <MenuItem key={f} value={f}>
                          {f}
                        </MenuItem>
                      ))}
                    </Select>
                    <Button size="small" onClick={() => handleReveal(e.id)}>
                      Reveal (audited)
                    </Button>
                    {revealField[e.id] && <Typography variant="caption">{revealField[e.id]}</Typography>}
                  </Stack>
                }
              />
            </ListItem>
          ))}
          {employees.length === 0 && (
            <Typography variant="body2" color="text.secondary">
              No employees yet.
            </Typography>
          )}
        </List>
      )}
    </Box>
  );
}

function OrgTab() {
  const [departments, setDepartments] = useState<DepartmentRow[]>([]);
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [deptName, setDeptName] = useState("");
  const [posCode, setPosCode] = useState("");
  const [posTitle, setPosTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    Promise.all([coreHrApi.departments(), coreHrApi.positions()])
      .then(([d, p]) => {
        setDepartments(d);
        setPositions(p);
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load org data")));
  };

  useEffect(load, []);

  const handleCreateDepartment = async () => {
    if (!deptName) return;
    try {
      await coreHrApi.createDepartment({ name: deptName });
      setDeptName("");
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to create department"));
    }
  };

  const handleCreatePosition = async () => {
    if (!posCode || !posTitle) return;
    try {
      await coreHrApi.createPosition({ code: posCode, title: posTitle });
      setPosCode("");
      setPosTitle("");
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to create position"));
    }
  };

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      <Typography variant="subtitle2" mb={1}>
        Departments
      </Typography>
      <Stack direction="row" spacing={1} mb={2}>
        <TextField size="small" label="Name" value={deptName} onChange={(e) => setDeptName(e.target.value)} />
        <Button size="small" variant="contained" onClick={handleCreateDepartment} disabled={!deptName}>
          Add department
        </Button>
      </Stack>
      <List dense disablePadding sx={{ mb: 2 }}>
        {departments.map((d) => (
          <ListItem key={d.id} divider>
            <ListItemText primary={d.name} />
          </ListItem>
        ))}
      </List>

      <Typography variant="subtitle2" mb={1}>
        Positions
      </Typography>
      <Stack direction="row" spacing={1} mb={2}>
        <TextField size="small" label="Code" value={posCode} onChange={(e) => setPosCode(e.target.value)} />
        <TextField size="small" label="Title" value={posTitle} onChange={(e) => setPosTitle(e.target.value)} />
        <Button size="small" variant="contained" onClick={handleCreatePosition} disabled={!posCode || !posTitle}>
          Add position
        </Button>
      </Stack>
      <List dense disablePadding>
        {positions.map((p) => (
          <ListItem key={p.id} divider>
            <ListItemText
              primary={
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography variant="body2">{p.title}</Typography>
                  <Chip label={p.code} size="small" variant="outlined" />
                  <Chip label={p.status} size="small" color={p.status === "vacant" ? "default" : "success"} />
                </Stack>
              }
            />
          </ListItem>
        ))}
        {positions.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            No positions yet.
          </Typography>
        )}
      </List>
    </Box>
  );
}

const TABS = ["Employees", "Org"] as const;

export default function CoreHrPanel() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Employees");

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" mb={1}>
          Core HR
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          {tr("settings.corehr.intro")}
        </Typography>
        <Tabs value={tab} onChange={(_e, value) => setTab(value)} sx={{ mb: 2 }}>
          {TABS.map((t) => (
            <Tab key={t} label={t} value={t} />
          ))}
        </Tabs>
        {tab === "Employees" && <EmployeesTab />}
        {tab === "Org" && <OrgTab />}
      </CardContent>
    </Card>
  );
}
