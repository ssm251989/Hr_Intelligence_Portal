import { useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { employeeRolesApi, type EmployeeRoleState, type RoleOption, type RoleResult } from "../../api/employeeRolesApi";
import { interviewersApi, type Pool } from "../../api/interviewersApi";
import { useT } from "../../i18n";

type Intent = "add" | "remove" | undefined;

// Part 22.4: Employees > Assign roles -- for one employee (tick exactly what they should have) or many
// (each role: tick = give to all, untick = take from all, dash = leave as it is).
export default function AssignRolesDialog({ employeeIds, onClose, onDone }: { employeeIds: string[]; onClose: () => void; onDone: (message: string) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const single = employeeIds.length === 1;
  const [roles, setRoles] = useState<RoleOption[] | null>(null);
  const [people, setPeople] = useState<EmployeeRoleState[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());  // single
  const [intent, setIntent] = useState<Record<string, Intent>>({});  // bulk
  const [createAccounts, setCreateAccounts] = useState(true);
  const [skills, setSkills] = useState("");
  const [pools, setPools] = useState<Pool[]>([]);
  const [poolIds, setPoolIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<RoleResult[] | null>(null);

  useEffect(() => {
    Promise.all([employeeRolesApi.catalog(), employeeRolesApi.state(employeeIds)])
      .then(([c, s]) => { setRoles(c.roles); setPeople(s.items); if (s.items.length === 1) setChosen(new Set(s.items[0].role_ids)); })
      .catch((err) => setError(extractErrorMessage(err, t("roles22.err"))));
    interviewersApi.pools().then((p) => setPools(p.filter((x) => x.active))).catch(() => setPools([]));
  }, [employeeIds, t]);

  const have = (roleId: string) => people.filter((p) => p.role_ids.includes(roleId)).length;
  const interviewerId = roles?.find((r) => r.key === "interviewer")?.id;
  const addingInterviewer = Boolean(interviewerId) && (single
    ? chosen.has(interviewerId!) && !people[0]?.role_ids.includes(interviewerId!)
    : intent[interviewerId!] === "add");
  const noAccount = people.filter((p) => !p.has_account);
  const changed = useMemo(() => single
    ? JSON.stringify([...chosen].sort()) !== JSON.stringify([...(people[0]?.role_ids ?? [])].sort())
    : Object.values(intent).some(Boolean), [single, chosen, intent, people]);

  const label = (r: RoleOption) => (r.key ? t(`roles22.role.${r.key}`) : r.name);
  const desc = (r: RoleOption) => (r.key ? t(`roles22.desc.${r.key}`) : r.description || t("roles22.desc.custom"));

  const toggle = (r: RoleOption) => {
    if (single) {
      setChosen((s) => { const n = new Set(s); if (n.has(r.id)) n.delete(r.id); else n.add(r.id); return n; });
      return;
    }
    const all = have(r.id) === people.length;
    const none = have(r.id) === 0;
    setIntent((m) => {
      const cur = m[r.id];
      // all -> remove -> (back); none -> add -> (back); mixed -> add -> remove -> (leave as it is)
      const next: Intent = all ? (cur ? undefined : "remove") : none ? (cur ? undefined : "add") : cur === undefined ? "add" : cur === "add" ? "remove" : undefined;
      return { ...m, [r.id]: next };
    });
  };
  const boxState = (r: RoleOption) => {
    if (single) return { checked: chosen.has(r.id), indeterminate: false };
    const i = intent[r.id];
    if (i === "add") return { checked: true, indeterminate: false };
    if (i === "remove") return { checked: false, indeterminate: false };
    const n = have(r.id);
    return { checked: n === people.length && n > 0, indeterminate: n > 0 && n < people.length };
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const add = Object.entries(intent).filter(([, v]) => v === "add").map(([k]) => k);
      const remove = Object.entries(intent).filter(([, v]) => v === "remove").map(([k]) => k);
      const r = await employeeRolesApi.apply({
        employee_ids: employeeIds, create_accounts: createAccounts,
        ...(single ? { set_role_ids: [...chosen] } : { add_role_ids: add, remove_role_ids: remove }),
        interviewer: addingInterviewer ? { skills: skills.split(",").map((s) => s.trim()).filter(Boolean), pool_ids: poolIds } : null,
      });
      const problems = r.results.filter((x) => x.result === "last_admin" || x.result === "error" || x.result === "no_account");
      if (problems.length) { setResults(r.results); return; }
      const n = r.results.filter((x) => x.result === "changed").length;
      onDone(n ? t("roles22.done", { n }) : t("roles22.nothing"));
    } catch (err) {
      setError(extractErrorMessage(err, t("roles22.err")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{single && people[0] ? t("roles22.title_one", { name: people[0].name }) : t("roles22.title_many", { n: employeeIds.length })}</DialogTitle>
      <DialogContent>
        {!roles ? (
          error ? <Alert severity="error">{error}</Alert> : <Box sx={{ display: "grid", placeItems: "center", py: 4 }}><CircularProgress /></Box>
        ) : (
          <Stack spacing={1.5} sx={{ mt: 0.5 }}>
            <Typography sx={{ fontSize: 13, color: f.muted }}>{single ? t("roles22.hint_one") : t("roles22.hint_many")}</Typography>
            {noAccount.length > 0 && (
              <Alert severity="info">
                {t("roles22.no_account", { names: noAccount.map((p) => p.name).join(", ") })}
                <FormControlLabel sx={{ display: "flex", mt: 0.5 }} control={<Checkbox size="small" checked={createAccounts} onChange={(e) => setCreateAccounts(e.target.checked)} />}
                  label={t("roles22.create_invite")} />
              </Alert>
            )}
            <Stack spacing={0.25}>
              {roles.map((r) => {
                const st = boxState(r);
                return (
                  <Stack key={r.id} direction="row" spacing={1} alignItems="flex-start" data-testid={`role-${r.key ?? r.name}`}
                    sx={{ p: 0.75, borderRadius: "10px", "&:hover": { bgcolor: f.surface2 } }}>
                    <Checkbox size="small" checked={st.checked} indeterminate={st.indeterminate} onChange={() => toggle(r)} inputProps={{ "aria-label": label(r) }} sx={{ mt: -0.5 }} />
                    <Box sx={{ minWidth: 0 }}>
                      <Typography sx={{ fontWeight: 700, fontSize: 14 }}>{label(r)}{!single && intent[r.id] ? ` - ${t(`roles22.intent.${intent[r.id]}`)}` : ""}</Typography>
                      <Typography sx={{ fontSize: 12, color: f.muted }}>{desc(r)}</Typography>
                    </Box>
                  </Stack>
                );
              })}
            </Stack>
            {addingInterviewer && (
              <Box sx={{ p: 1.5, borderRadius: "12px", bgcolor: f.skySoft }}>
                <Typography sx={{ fontWeight: 700, fontSize: 14, mb: 1 }}>{t("roles22.iv_title")}</Typography>
                <Stack spacing={1.25}>
                  <TextField size="small" label={t("roles22.iv_skills")} placeholder={t("roles22.iv_skills_ph")} value={skills} onChange={(e) => setSkills(e.target.value)} />
                  <Autocomplete multiple size="small" options={pools} getOptionLabel={(p) => p.job_title ? `${p.name} (${p.job_title})` : p.name}
                    value={pools.filter((p) => poolIds.includes(p.id))} onChange={(_e, v) => setPoolIds(v.map((p) => p.id))}
                    renderInput={(params) => <TextField {...params} label={t("roles22.iv_pools")} />} />
                </Stack>
              </Box>
            )}
            {single && people[0]?.other_roles.length ? (
              <Typography sx={{ fontSize: 12, color: f.muted }}>{t("roles22.other", { roles: people[0].other_roles.join(", ") })}</Typography>
            ) : null}
            <Typography sx={{ fontSize: 12, color: f.muted }}>{t("roles22.effect")}</Typography>
            {error && <Alert severity="error">{error}</Alert>}
            {results && (
              <Alert severity="warning">
                {results.map((x) => (
                  <div key={x.employee_id}>{x.name}: {x.result === "changed" ? t("roles22.r.changed") : x.result === "unchanged" ? t("roles22.r.unchanged")
                    : x.result === "no_account" ? t("roles22.r.no_account") : x.error}</div>
                ))}
              </Alert>
            )}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={results ? () => onDone(t("roles22.done", { n: results.filter((x) => x.result === "changed").length })) : onClose}>
          {results ? t("roles22.close") : t("roles22.cancel")}
        </Button>
        {!results && <Button variant="contained" onClick={save} disabled={busy || !roles || !changed}>{busy ? t("roles22.saving") : t("roles22.save")}</Button>}
      </DialogActions>
    </Dialog>
  );
}
