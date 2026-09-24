import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, iamApi, usersApi, type PermissionRow, type RoleRow } from "../api/client";
import type { UserRead } from "../api/types";

// Part 5A (docs/HRMS_COMPLETE_SPEC.txt section 4's UI, scoped down the same way every
// other part's admin surface has been): a roles list with a permission-checkbox editor
// and an "assign role to user" dialog, plus an access-review lookup. Deliberately NOT the
// full spec vision (a role x action matrix grid, a scope editor with condition_jsonlogic
// builder, "view as user" impersonation UI) -- see docs/build_log.md's own Part 5 note.

function RoleEditorDialog({ open, onClose, role, permissions, onSaved, onError }: {
  open: boolean;
  onClose: () => void;
  role: RoleRow | null;
  permissions: PermissionRow[];
  onSaved: () => void;
  onError: (message: string) => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setSelected(new Set(role?.permissions ?? []));
  }, [role]);

  const modules = Array.from(new Set(permissions.map((p) => p.module)));

  const toggle = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const handleSave = async () => {
    if (!role) return;
    setSaving(true);
    try {
      await iamApi.updateRole(role.id, { permissions: Array.from(selected) });
      onSaved();
      onClose();
    } catch (err) {
      onError(extractErrorMessage(err, "Failed to update role"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{role?.name}</DialogTitle>
      <DialogContent>
        {modules.map((module) => (
          <Box key={module} mb={2}>
            <Typography variant="subtitle2" textTransform="capitalize" mb={0.5}>
              {module}
            </Typography>
            <Stack>
              {permissions
                .filter((p) => p.module === module)
                .map((p) => (
                  <FormControlLabel
                    key={p.code}
                    control={<Checkbox size="small" checked={selected.has(p.code)} onChange={() => toggle(p.code)} />}
                    label={`${p.resource}.${p.action}`}
                  />
                ))}
            </Stack>
          </Box>
        ))}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function RolesTab() {
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [permissions, setPermissions] = useState<PermissionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<RoleRow | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([iamApi.roles(), iamApi.permissions()])
      .then(([r, p]) => {
        setRoles(r);
        setPermissions(p);
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load roles")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {loading ? (
        <CircularProgress size={24} />
      ) : (
        <List dense disablePadding>
          {roles.map((r) => (
            <ListItem key={r.id} divider secondaryAction={<Button size="small" onClick={() => setEditing(r)}>Edit permissions</Button>}>
              <ListItemText
                primary={
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="body2">{r.name}</Typography>
                    {r.is_system && <Chip label="system" size="small" variant="outlined" />}
                  </Stack>
                }
                secondary={`${r.permissions.length} permission(s)`}
              />
            </ListItem>
          ))}
        </List>
      )}
      <RoleEditorDialog open={editing !== null} onClose={() => setEditing(null)} role={editing} permissions={permissions} onSaved={load} onError={setError} />
    </Box>
  );
}

function AssignmentsTab() {
  const [users, setUsers] = useState<UserRead[]>([]);
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [selectedUser, setSelectedUser] = useState<UserRead | null>(null);
  const [assignments, setAssignments] = useState<Awaited<ReturnType<typeof iamApi.roleAssignments>>>([]);
  const [roleToAssign, setRoleToAssign] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([usersApi.list(), iamApi.roles()])
      .then(([u, r]) => {
        setUsers(u);
        setRoles(r);
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load users/roles")));
  }, []);

  const loadAssignments = (userId: string) => {
    iamApi
      .roleAssignments(userId)
      .then(setAssignments)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load role assignments")));
  };

  const handleSelectUser = (user: UserRead) => {
    setSelectedUser(user);
    loadAssignments(user.id);
  };

  const handleAssign = async () => {
    if (!selectedUser || !roleToAssign) return;
    try {
      await iamApi.createRoleAssignment({ user_id: selectedUser.id, role_id: roleToAssign, scope_type: "all" });
      loadAssignments(selectedUser.id);
      setRoleToAssign("");
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to assign role"));
    }
  };

  const handleRevoke = async (id: string) => {
    try {
      await iamApi.deleteRoleAssignment(id);
      if (selectedUser) loadAssignments(selectedUser.id);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to revoke role"));
    }
  };

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      <Stack direction="row" spacing={3}>
        <Box flex={1}>
          <Typography variant="subtitle2" mb={1}>
            Users
          </Typography>
          <List dense disablePadding sx={{ maxHeight: 320, overflow: "auto" }}>
            {users.map((u) => (
              <ListItem key={u.id} divider component="div" onClick={() => handleSelectUser(u)} sx={{ cursor: "pointer", bgcolor: selectedUser?.id === u.id ? "action.selected" : undefined }}>
                <ListItemText primary={u.full_name || u.email} secondary={u.email} />
              </ListItem>
            ))}
          </List>
        </Box>
        <Box flex={1}>
          {selectedUser ? (
            <>
              <Typography variant="subtitle2" mb={1}>
                Roles for {selectedUser.email}
              </Typography>
              <Stack direction="row" spacing={1} mb={2}>
                <Select size="small" value={roleToAssign} onChange={(e) => setRoleToAssign(e.target.value)} displayEmpty sx={{ minWidth: 200 }}>
                  <MenuItem value="">
                    <em>Choose a role</em>
                  </MenuItem>
                  {roles.map((r) => (
                    <MenuItem key={r.id} value={r.id}>
                      {r.name}
                    </MenuItem>
                  ))}
                </Select>
                <Button size="small" variant="contained" onClick={handleAssign} disabled={!roleToAssign}>
                  Assign
                </Button>
              </Stack>
              <List dense disablePadding>
                {assignments.map((a) => (
                  <ListItem key={a.id} divider secondaryAction={<Button size="small" onClick={() => handleRevoke(a.id)}>Revoke</Button>}>
                    <ListItemText primary={roles.find((r) => r.id === a.role_id)?.name ?? a.role_id} secondary={`scope: ${a.scope_type}`} />
                  </ListItem>
                ))}
              </List>
            </>
          ) : (
            <Typography variant="body2" color="text.secondary">
              Select a user to manage their roles.
            </Typography>
          )}
        </Box>
      </Stack>
    </Box>
  );
}

function AccessReviewTab() {
  const [permission, setPermission] = useState("");
  const [permissions, setPermissions] = useState<PermissionRow[]>([]);
  const [rows, setRows] = useState<Awaited<ReturnType<typeof iamApi.accessReview>>>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    iamApi.permissions().then(setPermissions).catch(() => undefined);
  }, []);

  const handleLookup = async () => {
    if (!permission) return;
    try {
      setRows(await iamApi.accessReview(permission));
      setError(null);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to run access review"));
    }
  };

  return (
    <Box>
      <Typography variant="body2" color="text.secondary" mb={2}>
        "Who can see salary / Aadhaar" -- pick a permission and see every user who
        currently holds it.
      </Typography>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      <Stack direction="row" spacing={1} mb={2}>
        <Select size="small" value={permission} onChange={(e) => setPermission(e.target.value)} displayEmpty sx={{ minWidth: 260 }}>
          <MenuItem value="">
            <em>Choose a permission</em>
          </MenuItem>
          {permissions.map((p) => (
            <MenuItem key={p.code} value={p.code}>
              {p.code}
            </MenuItem>
          ))}
        </Select>
        <Button size="small" variant="contained" onClick={handleLookup} disabled={!permission}>
          Look up
        </Button>
      </Stack>
      <List dense disablePadding>
        {rows.map((r) => (
          <ListItem key={r.user_id} divider>
            <ListItemText primary={r.full_name || r.email} secondary={`${r.email} -- via ${r.role_names.join(", ")}`} />
          </ListItem>
        ))}
      </List>
    </Box>
  );
}

const TABS = ["Roles", "Assignments", "Access review"] as const;

export default function AccessControlPanel() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Roles");

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" mb={1}>
          Access Control
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          Roles, permissions, and who has access to what (Part 5A's IAM/RBAC) -- sits
          alongside the existing recruiter/hiring_manager/interviewer/admin roles, not in
          place of them.
        </Typography>
        <Tabs value={tab} onChange={(_e, value) => setTab(value)} sx={{ mb: 2 }}>
          {TABS.map((t) => (
            <Tab key={t} label={t} value={t} />
          ))}
        </Tabs>
        {tab === "Roles" && <RolesTab />}
        {tab === "Assignments" && <AssignmentsTab />}
        {tab === "Access review" && <AccessReviewTab />}
      </CardContent>
    </Card>
  );
}
