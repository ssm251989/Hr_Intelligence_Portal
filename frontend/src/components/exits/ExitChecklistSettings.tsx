import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";

import { extractErrorMessage } from "../../api/client";
import { exitChecklistApi, type ChecklistConfigItem, type ChecklistSettings } from "../../api/exitChecklistApi";
import { useT } from "../../i18n";

// feat 2026-10-06: Settings > Onboarding & employees > Exit checklist -- the items every exit gets, the owner,
// due days before the last working day, required or optional and how each one completes.

export default function ExitChecklistSettingsPage() {
  const t = useT();
  const [cfg, setCfg] = useState<ChecklistSettings | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { exitChecklistApi.settings().then(setCfg).catch((e) => setMsg({ ok: false, text: extractErrorMessage(e, "") })); }, []);
  if (!cfg) return msg ? <Alert severity="error">{msg.text}</Alert> : <Skeleton variant="rounded" height={300} />;

  const setItem = (i: number, patch: Partial<ChecklistConfigItem>) => setCfg({ ...cfg, items: cfg.items.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
  const add = () => setCfg({ ...cfg, items: [...cfg.items, { key: `item_${Date.now().toString(36)}`, title: "", owner_role: "hr", due_days_before: 0, required: true, auto: "manual" }] });
  const save = async () => {
    setMsg(null);
    try {
      setCfg(await exitChecklistApi.saveSettings(cfg.items));
      setMsg({ ok: true, text: t("xc.set.saved") });
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, "") });
    }
  };

  return (
    <Stack spacing={2}>
      <Typography color="text.secondary">{t("xc.set.intro")}</Typography>
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      {cfg.items.map((it, i) => (
        <Card key={it.key} variant="outlined">
          <CardContent>
            <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
              <Typography sx={{ fontWeight: 800, flex: 1 }}>{t("xc.set.item", { n: i + 1 })}</Typography>
              <Tooltip title={t("xc.set.remove")}>
                <IconButton aria-label={t("xc.set.remove")} onClick={() => setCfg({ ...cfg, items: cfg.items.filter((_, j) => j !== i) })}><DeleteOutlineIcon /></IconButton>
              </Tooltip>
            </Stack>
            <Stack spacing={1.5}>
              <TextField label={t("xc.set.title")} value={it.title} onChange={(e) => setItem(i, { title: e.target.value })} fullWidth />
              <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
                <TextField select label={t("xc.set.owner")} value={it.owner_role} onChange={(e) => setItem(i, { owner_role: e.target.value })} sx={{ minWidth: 180 }}>
                  {cfg.owner_roles.map((r) => <MenuItem key={r} value={r}>{t(`xc.role.${r}`)}</MenuItem>)}
                </TextField>
                <TextField label={t("xc.set.owner_email")} helperText={t("xc.set.owner_email_hint")} value={it.owner_email ?? ""} disabled={it.owner_role === "manager"}
                  onChange={(e) => setItem(i, { owner_email: e.target.value || null })} sx={{ flex: 1 }} />
                <TextField type="number" label={t("xc.set.due")} value={it.due_days_before} inputProps={{ min: 0, max: 60 }}
                  onChange={(e) => setItem(i, { due_days_before: Math.max(0, Number(e.target.value) || 0) })} sx={{ width: 220 }} />
              </Stack>
              <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }}>
                <TextField select label={t("xc.set.auto")} value={it.auto} onChange={(e) => setItem(i, { auto: e.target.value, kind: undefined })} sx={{ minWidth: 260 }}>
                  {cfg.auto_rules.map((r) => <MenuItem key={r} value={r}>{t(`xc.set.auto.${r}`)}</MenuItem>)}
                </TextField>
                {it.auto === "asset_return" && (
                  <TextField label={t("xc.set.cards")} defaultValue={(it.cards ?? []).join(", ")} sx={{ flex: 1 }}
                    onBlur={(e) => setItem(i, { cards: e.target.value.split(",").map((c) => c.trim()).filter(Boolean) })} />
                )}
                <FormControlLabel control={<Switch checked={it.required} onChange={(e) => setItem(i, { required: e.target.checked })} />} label={t("xc.set.required")} />
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      ))}
      <Stack direction="row" spacing={1}>
        <Button onClick={add}>{t("xc.set.add")}</Button>
        <Button variant="contained" onClick={save}>{t("xc.set.save")}</Button>
      </Stack>
    </Stack>
  );
}
