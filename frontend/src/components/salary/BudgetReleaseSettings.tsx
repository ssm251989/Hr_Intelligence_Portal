import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import FormControlLabel from "@mui/material/FormControlLabel";
import Radio from "@mui/material/Radio";
import RadioGroup from "@mui/material/RadioGroup";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, platformSettingsApi } from "../../api/client";
import { useT } from "../../i18n";

const ON = "recruitment.budgets.release_on_exit";
const MODE = "recruitment.budgets.release_mode";

// Part 21.7: Settings > Hiring > Budgets -- when someone exits, their salary goes back to the department budget.
export default function BudgetReleaseSettings() {
  const t = useT();
  const [on, setOn] = useState<boolean | null>(null);
  const [mode, setMode] = useState("pro_rata");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    Promise.all([platformSettingsApi.definitions(), platformSettingsApi.values()]).then(([defs, vals]) => {
      const v = (k: string) => vals.find((x) => x.key === k && x.scope_type === "tenant")?.value ?? defs.find((d) => d.key === k)?.default;
      setOn(v(ON) !== false);
      setMode(String(v(MODE) ?? "pro_rata"));
    }).catch((e) => setMsg({ ok: false, text: extractErrorMessage(e, t("budget21.err")) }));
  }, [t]);

  const save = async (key: string, value: unknown) => {
    try {
      await platformSettingsApi.update(key, value);
      setMsg({ ok: true, text: t("budget21.saved") });
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, t("budget21.err")) });
    }
  };
  if (on === null) return null;
  return (
    <Stack spacing={0.5} sx={{ mb: 2, p: 1.5, borderRadius: "12px", bgcolor: "action.hover" }} data-testid="budget-release-settings">
      <FormControlLabel control={<Switch checked={on} onChange={(e) => { setOn(e.target.checked); void save(ON, e.target.checked); }} />}
        label={<Typography sx={{ fontWeight: 700 }}>{t("budget21.on")}</Typography>} />
      <Typography variant="body2" color="text.secondary">{t("budget21.on_hint")}</Typography>
      {on && (
        <RadioGroup value={mode} onChange={(e) => { setMode(e.target.value); void save(MODE, e.target.value); }} sx={{ pl: 1 }}>
          <FormControlLabel value="pro_rata" control={<Radio size="small" />} label={t("budget21.pro_rata")} />
          <FormControlLabel value="full" control={<Radio size="small" />} label={t("budget21.full")} />
        </RadioGroup>
      )}
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}
    </Stack>
  );
}
