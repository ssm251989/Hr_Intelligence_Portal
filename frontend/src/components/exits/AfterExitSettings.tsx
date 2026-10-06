// Part 21.2: Settings > Onboarding & employees > After exit -- which hiring data moves to the Recycle bin when an exit is
// completed, and after how many days. The employee record, signed offer, joining documents, BGV, letters and the exit
// record are always kept.
import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, platformSettingsApi } from "../../api/client";
import { useT } from "../../i18n";

const CATS = ["candidate_profile", "applications_interviews", "links_forms", "inbox_emails", "portal_access"];
const K = { on: "employees.after_exit.move_hiring_data", days: "employees.after_exit.days", cats: "employees.after_exit.categories" };

export default function AfterExitSettings() {
  const t = useT();
  const [on, setOn] = useState(true);
  const [days, setDays] = useState(0);
  const [cats, setCats] = useState<string[] | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    Promise.all([platformSettingsApi.definitions(), platformSettingsApi.values()]).then(([defs, vals]) => {
      const v = (k: string) => vals.find((x) => x.key === k && x.scope_type === "tenant")?.value ?? defs.find((d) => d.key === k)?.default;
      setOn(v(K.on) !== false);
      setDays(Number(v(K.days) ?? 0));
      setCats((v(K.cats) as string[]) ?? CATS);
    }).catch((e) => setMsg({ ok: false, text: extractErrorMessage(e, "") }));
  }, []);
  if (!cats) return msg ? <Alert severity="error">{msg.text}</Alert> : <Skeleton variant="rounded" height={260} />;
  const save = async () => {
    setMsg(null);
    try {
      await platformSettingsApi.update(K.on, on);
      await platformSettingsApi.update(K.days, Math.max(0, Math.round(days) || 0));
      await platformSettingsApi.update(K.cats, cats);
      setMsg({ ok: true, text: t("ax.saved") });
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, "") });
    }
  };
  return (
    <Stack spacing={2} data-testid="after-exit-settings">
      <Typography color="text.secondary">{t("ax.intro")}</Typography>
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      <Card variant="outlined" sx={{ p: 2 }}>
        <FormControlLabel control={<Switch checked={on} onChange={(e) => setOn(e.target.checked)} />} label={<Typography sx={{ fontWeight: 800 }}>{t("ax.on")}</Typography>} />
        <TextField type="number" label={t("ax.days")} helperText={t("ax.days_hint")} value={days} disabled={!on} inputProps={{ min: 0, max: 365 }}
          onChange={(e) => setDays(Number(e.target.value))} sx={{ mt: 1.5, maxWidth: 320, display: "block" }} />
        <Typography sx={{ fontWeight: 700, mt: 2 }}>{t("ax.moves")}</Typography>
        <Stack>
          {CATS.map((c) => (
            <FormControlLabel key={c} disabled={!on} label={t(`ax.cat.${c}`)}
              control={<Checkbox checked={cats.includes(c)} onChange={(e) => setCats(e.target.checked ? [...cats, c] : cats.filter((x) => x !== c))} />} />
          ))}
        </Stack>
        <Alert severity="info" sx={{ mt: 1.5 }}>{t("ax.kept")}</Alert>
      </Card>
      <Stack direction="row"><Button variant="contained" onClick={save}>{t("ax.save")}</Button></Stack>
    </Stack>
  );
}
