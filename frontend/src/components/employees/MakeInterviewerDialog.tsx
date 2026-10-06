// Part 20.4: HR makes an employee an interviewer -- Interviewer role, availability (Mon-Fri 10-18, they change it
// under My availability), skills, max a day, and the pools they join. Or takes them off interviewing.
import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, http } from "../../api/client";
import type { EmployeeRow } from "../../api/employeesApi";
import { useT } from "../../i18n";

interface Setup { pools: { id: string; name: string; skills: string[]; member: boolean }[]; availability: { email: string; skills: string[]; max_per_day: number | null } | null }
const B = "/api/v1/ui/self-service/employees";

export default function MakeInterviewerDialog({ row, remove, onClose, onToast }: { row: EmployeeRow; remove?: boolean; onClose: () => void; onToast: (m: string) => void }) {
  const t = useT();
  const [setup, setSetup] = useState<Setup | null>(null);
  const [pools, setPools] = useState<string[]>([]);
  const [skills, setSkills] = useState("");
  const [max, setMax] = useState("3");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    http.get<Setup>(`${B}/${row.id}/interviewer`).then((s) => {
      setSetup(s);
      setPools(s.pools.filter((p) => p.member).map((p) => p.id));
      setSkills((s.availability?.skills ?? []).join(", "));
      if (s.availability?.max_per_day) setMax(String(s.availability.max_per_day));
    }).catch((e) => setError(extractErrorMessage(e, "")));
  }, [row.id]);
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      if (remove) {
        await http.post(`${B}/${row.id}/remove-interviewer`, {});
        onToast(t("iv20.removed"));
      } else {
        const r = await http.post<{ email: string; pools: string[] }>(`${B}/${row.id}/make-interviewer`, {
          pool_ids: pools, skills: skills.split(",").map((x) => x.trim()).filter(Boolean), max_per_day: Number(max) || null,
        });
        onToast(t("iv20.made", { email: r.email }));
      }
      onClose();
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm" aria-labelledby="iv20-make-title">
      <DialogTitle id="iv20-make-title">{t(remove ? "iv20.remove_title" : "iv20.make_title", { name: row.name })}</DialogTitle>
      <DialogContent dividers>
        {!setup && !error ? <Skeleton variant="rounded" height={160} /> : remove ? (
          <Typography>{t("iv20.remove_text")}</Typography>
        ) : (
          <Stack spacing={1.5}>
            <Typography sx={{ fontSize: 13, color: "text.secondary" }}>{t("iv20.make_hint")}</Typography>
            <TextField label={t("iv20.skills")} placeholder={t("iv20.skills_ph")} value={skills} onChange={(e) => setSkills(e.target.value)} />
            <TextField type="number" label={t("iv20.max_per_day")} value={max} onChange={(e) => setMax(e.target.value)} inputProps={{ min: 1, max: 10 }} sx={{ maxWidth: 220 }} />
            <Typography sx={{ fontWeight: 700 }}>{t("iv20.pools")}</Typography>
            {(setup?.pools ?? []).length === 0 && <Typography sx={{ fontSize: 13, color: "text.secondary" }}>{t("iv20.no_pools")}</Typography>}
            {(setup?.pools ?? []).map((p) => (
              <FormControlLabel key={p.id} label={`${p.name}${p.skills.length ? ` - ${p.skills.slice(0, 4).join(", ")}` : ""}`}
                control={<Checkbox checked={pools.includes(p.id)} onChange={(e) => setPools(e.target.checked ? [...pools, p.id] : pools.filter((x) => x !== p.id))} />} />
            ))}
          </Stack>
        )}
        {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" color={remove ? "error" : "primary"} onClick={go} disabled={busy || !setup}>{t(remove ? "iv20.remove" : "iv20.make")}</Button>
      </DialogActions>
    </Dialog>
  );
}
