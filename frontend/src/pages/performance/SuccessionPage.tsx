import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { performanceExtraApi, type CriticalRole, type PersonPick } from "../../api/performanceExtra";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { NoAccess, PerfChip, useDateFormat, useFresh } from "../../components/performance/shared";
import { useT } from "../../i18n";
import { Cell, EmptyState, Emoji, FriendlyError, InfoTip, PageGrid, PageHeader, StatTile, UserAvatar, explainError } from "../../ui-kit";

// Part 15.6: succession -- every critical role, who holds it today, and who could step in
// (ready now / in 1-2 years / in 3+ years).

const READINESS = ["ready_now", "ready_1_2_years", "ready_3_plus_years"] as const;

function AddSuccessorDialog({ open, roles, initialRole, onClose, onSaved }: { open: boolean; roles: CriticalRole[]; initialRole: string; onClose: () => void; onSaved: (msg: string) => void }) {
  const t = useT();
  const [role, setRole] = useState(initialRole);
  const [person, setPerson] = useState<PersonPick | null>(null);
  const [options, setOptions] = useState<PersonPick[]>([]);
  const [query, setQuery] = useState("");
  const [readiness, setReadiness] = useState<string>("ready_1_2_years");
  const [rank, setRank] = useState("1");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setRole(initialRole), [initialRole]);
  useEffect(() => {
    if (!open) return;
    const h = window.setTimeout(() => {
      performanceExtraApi.people(query).then(setOptions).catch(() => setOptions([]));
    }, 250);
    return () => window.clearTimeout(h);
  }, [query, open]);

  const save = async () => {
    if (!person || !role) return;
    setSaving(true);
    setError(null);
    try {
      await performanceExtraApi.addSuccessor(role, { employee_id: person.id, readiness, rank: Number(rank) || 1 });
      onSaved(t("succession.added", { name: person.name, role: roles.find((r) => r.position_id === role)?.title ?? "" }));
      setPerson(null);
      onClose();
    } catch (err) {
      const e = explainError(err);
      setError(`${e.what} ${e.fix}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("succession.add_title")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField select label={t("succession.role")} value={role} onChange={(e) => setRole(e.target.value)} helperText={t("succession.role_hint")}>
            {roles.map((r) => <MenuItem key={r.position_id} value={r.position_id}>{r.title}</MenuItem>)}
          </TextField>
          <Autocomplete
            options={options}
            value={person}
            onChange={(_, v) => setPerson(v)}
            onInputChange={(_, v) => setQuery(v)}
            getOptionLabel={(o) => o.name}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            filterOptions={(x) => x}
            noOptionsText={t("succession.no_people")}
            renderOption={(props, o) => (
              <li {...props} key={o.id}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <UserAvatar name={o.name} size={26} />
                  <span>{o.name}{o.designation ? ` · ${o.designation}` : ""}</span>
                </Stack>
              </li>
            )}
            renderInput={(params) => <TextField {...params} label={t("succession.person")} placeholder={t("succession.person_placeholder")} helperText={t("succession.person_hint")} />}
          />
          <TextField select label={t("succession.readiness")} value={readiness} onChange={(e) => setReadiness(e.target.value)} helperText={t("succession.readiness_tip")}>
            {READINESS.map((r) => <MenuItem key={r} value={r}>{t(`performance.status.${r}`)}</MenuItem>)}
          </TextField>
          <TextField label={t("succession.rank")} type="number" placeholder="1" value={rank} onChange={(e) => setRank(e.target.value)} helperText={t("succession.rank_hint")} slotProps={{ htmlInput: { min: 1, max: 20 } }} />
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={saving || !person || !role}>{saving ? t("succession.saving") : t("succession.save")}</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function SuccessionPage() {
  const t = useT();
  const f = useFresh();
  const date = useDateFormat();
  const { can, loading: bootLoading } = useMeBootstrap();
  const allowed = can("performance.succession.view");
  const [data, setData] = useState<{ positions: CriticalRole[]; can_edit: boolean } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [dialogRole, setDialogRole] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    performanceExtraApi.succession().then(setData).catch(setError);
  }, []);
  useEffect(() => {
    if (allowed) load();
  }, [allowed, load]);

  if (bootLoading) return null;
  const roles = data?.positions ?? [];
  const canEdit = Boolean(data?.can_edit);
  const header = (
    <PageHeader
      emoji="seedling"
      title={t("succession.title")}
      purpose={t("succession.purpose")}
      tourKey="succession"
      primary={canEdit && roles.length ? <Button variant="contained" onClick={() => setDialogRole(roles[0].position_id)} startIcon={<Emoji name="seedling" size={16} />}>{t("succession.add")}</Button> : undefined}
    />
  );
  if (!allowed) {
    return (
      <Box>
        {header}
        <NoAccess what={t("succession.title")} />
      </Box>
    );
  }
  const covered = roles.filter((r) => r.coverage === "covered").length;
  const atRisk = roles.filter((r) => r.coverage === "at_risk").length;
  const none = roles.filter((r) => r.coverage === "uncovered").length;

  return (
    <Box>
      {header}
      {notice && <Alert severity="success" onClose={() => setNotice(null)} sx={{ mb: 2 }}>{notice}</Alert>}
      {error ? (
        <FriendlyError error={error} onRetry={load} />
      ) : (
        <>
          <PageGrid sx={{ mb: 2.25 }}>
            <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="building" value={roles.length} label={t("succession.stat.roles", { count: roles.length })} loading={!data} /></Cell>
            <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="check" value={covered} label={t("succession.stat.covered", { count: covered })} tone="ok" loading={!data} /></Cell>
            <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="warning" value={atRisk} label={t("succession.stat.at_risk", { count: atRisk })} tone={atRisk ? "sun" : "ok"} loading={!data} /></Cell>
            <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="fire" value={none} label={t("succession.stat.none", { count: none })} tone={none ? "coral" : "ok"} loading={!data} /></Cell>
          </PageGrid>

          {data && roles.length === 0 ? (
            <Card>
              <EmptyState illustration="team-spirit" title={t("succession.empty")} hint={t("succession.empty_hint")} />
            </Card>
          ) : (
            <PageGrid>
              {roles.map((r) => (
                <Cell key={r.position_id} span={{ xs: 12, md: 6, xl: 4 }}>
                  <Card sx={{ p: 2.25, display: "flex", flexDirection: "column", gap: 1.5 }}>
                    <Stack direction="row" spacing={1} alignItems="flex-start">
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography variant="h3" component="h2" sx={{ fontSize: 17, fontWeight: 800 }}>{r.title}</Typography>
                        <Typography sx={{ fontSize: 13, color: f.muted }}>
                          {[r.department, r.grade ? t("succession.grade", { grade: r.grade }) : null].filter(Boolean).join(" · ") || " "}
                        </Typography>
                      </Box>
                      <PerfChip status={r.coverage} />
                    </Stack>
                    <Typography sx={{ fontSize: 13 }}>
                      <Emoji name="id_card" size={14} /> {r.holders.length ? t("succession.held_by", { names: r.holders.join(", ") }) : t("succession.vacant")}
                    </Typography>
                    <Box>
                      <Typography sx={{ fontWeight: 700, fontSize: 14, mb: 0.75 }}>
                        {t("succession.successors", { count: r.successors.length })}
                        <InfoTip text={t("succession.readiness_tip")} />
                      </Typography>
                      {r.successors.length === 0 ? (
                        <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("succession.no_successors")}</Typography>
                      ) : (
                        <Stack spacing={0.75} component="ol" sx={{ m: 0, p: 0, listStyle: "none" }}>
                          {r.successors.map((s) => (
                            <Stack key={s.employee_id} component="li" direction="row" spacing={1} alignItems="center" sx={{ p: 1, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                              <Typography sx={{ width: 22, fontWeight: 800, color: f.muted, textAlign: "center" }} aria-label={t("succession.rank_n", { rank: s.rank })}>{s.rank}</Typography>
                              <UserAvatar name={s.name || "?"} size={30} />
                              <Box sx={{ flex: 1, minWidth: 0 }}>
                                <Typography sx={{ fontWeight: 700, fontSize: 14 }} noWrap>{s.name || t("performance.someone")}</Typography>
                                {s.assessed_at && <Typography sx={{ fontSize: 11, color: f.muted }}>{t("succession.assessed", { date: date(s.assessed_at) })}</Typography>}
                              </Box>
                              <PerfChip status={s.readiness} />
                            </Stack>
                          ))}
                        </Stack>
                      )}
                    </Box>
                    {canEdit && (
                      <Box sx={{ mt: "auto" }}>
                        <Button size="small" onClick={() => setDialogRole(r.position_id)}>＋ {t("succession.add_for", { role: r.title })}</Button>
                      </Box>
                    )}
                  </Card>
                </Cell>
              ))}
            </PageGrid>
          )}
        </>
      )}
      <AddSuccessorDialog open={dialogRole !== null} roles={roles} initialRole={dialogRole ?? ""} onClose={() => setDialogRole(null)} onSaved={(m) => { setNotice(m); load(); }} />
    </Box>
  );
}
