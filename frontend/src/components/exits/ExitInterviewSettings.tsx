import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
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
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { exitInterviewApi, type ExitInterviewSettings as Settings, type ExitQuestion, type QuestionType } from "../../api/exitInterviewApi";
import { useT } from "../../i18n";

// fix 2026-10-06: Settings > Onboarding & employees > Exit interview -- the questions the leaving
// EMPLOYEE answers (add / remove / reorder; text, stars, Yes/Maybe/No, choice list; required or not --
// default all optional; en/hi/ta), AI summary on/off and reminder days before the last working day.

const TYPES: QuestionType[] = ["text", "stars", "yes_maybe_no", "choice"];

export default function ExitInterviewSettingsPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [cfg, setCfg] = useState<Settings | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { exitInterviewApi.settings().then(setCfg).catch((e) => setMsg({ ok: false, text: extractErrorMessage(e, "") })); }, []);
  if (!cfg) return msg ? <Alert severity="error">{msg.text}</Alert> : <Skeleton variant="rounded" height={300} />;

  const setQ = (i: number, patch: Partial<ExitQuestion>) => setCfg({ ...cfg, questions: cfg.questions.map((q, j) => (j === i ? { ...q, ...patch } : q)) });
  const move = (i: number, d: number) => {
    const qs = [...cfg.questions];
    const [x] = qs.splice(i, 1);
    qs.splice(i + d, 0, x);
    setCfg({ ...cfg, questions: qs });
  };
  const add = () => setCfg({ ...cfg, questions: [...cfg.questions, { id: `q${Date.now().toString(36)}`, type: "text", required: false, label: { en: "" } }] });
  const save = async () => {
    setMsg(null);
    try {
      setCfg(await exitInterviewApi.saveSettings(cfg));
      setMsg({ ok: true, text: t("exitq.set.saved") });
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, "") });
    }
  };

  return (
    <Stack spacing={2}>
      <Typography color="text.secondary">{t("exitq.set.intro")}</Typography>
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      <Card>
        <CardContent>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
            <FormControlLabel control={<Switch checked={cfg.ai_summary} onChange={(e) => setCfg({ ...cfg, ai_summary: e.target.checked })} />} label={t("exitq.set.ai")} />
            <TextField type="number" size="small" label={t("exitq.set.reminder")} value={cfg.reminder_days} helperText={t("exitq.set.reminder_hint")}
              onChange={(e) => setCfg({ ...cfg, reminder_days: Math.max(0, Math.min(30, Number(e.target.value) || 0)) })} inputProps={{ min: 0, max: 30 }} />
          </Stack>
        </CardContent>
      </Card>
      {cfg.questions.map((q, i) => (
        <Card key={q.id} data-testid={`exitq-${q.id}`}>
          <CardContent>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Typography sx={{ fontWeight: 800, flex: 1 }}>{t("exitq.set.question", { n: i + 1 })}</Typography>
              <Tooltip title={t("exitq.set.up")}><span><IconButton size="small" disabled={i === 0} onClick={() => move(i, -1)} aria-label={t("exitq.set.up")}><ArrowUpwardIcon fontSize="small" /></IconButton></span></Tooltip>
              <Tooltip title={t("exitq.set.down")}><span><IconButton size="small" disabled={i === cfg.questions.length - 1} onClick={() => move(i, 1)} aria-label={t("exitq.set.down")}><ArrowDownwardIcon fontSize="small" /></IconButton></span></Tooltip>
              <Tooltip title={t("exitq.set.remove")}><IconButton size="small" onClick={() => setCfg({ ...cfg, questions: cfg.questions.filter((_, j) => j !== i) })} aria-label={t("exitq.set.remove")}><DeleteOutlineIcon fontSize="small" /></IconButton></Tooltip>
            </Stack>
            <Box sx={{ display: "grid", gap: 1.25, gridTemplateColumns: { xs: "1fr", md: "1fr 1fr 1fr" } }}>
              {(["en", "hi", "ta"] as const).map((l) => (
                <TextField key={l} size="small" label={t(`exitq.set.lang.${l}`)} required={l === "en"} value={q.label[l] ?? ""} onChange={(e) => setQ(i, { label: { ...q.label, [l]: e.target.value } })} />
              ))}
            </Box>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }} sx={{ mt: 1.25 }}>
              <TextField select size="small" label={t("exitq.set.type")} value={q.type} onChange={(e) => setQ(i, { type: e.target.value as QuestionType })} sx={{ minWidth: 200 }}>
                {TYPES.map((x) => <MenuItem key={x} value={x}>{t(`exitq.type.${x}`)}</MenuItem>)}
              </TextField>
              {q.type === "choice" && (
                <TextField size="small" fullWidth label={t("exitq.set.options")} helperText={t("exitq.set.options_hint")} value={(q.options ?? []).join(", ")}
                  onChange={(e) => setQ(i, { options: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} />
              )}
              <FormControlLabel control={<Switch checked={q.required} onChange={(e) => setQ(i, { required: e.target.checked })} />} label={q.required ? t("jform.show.required") : t("jform.show.optional")} />
            </Stack>
          </CardContent>
        </Card>
      ))}
      <Box sx={{ position: "sticky", bottom: 12, zIndex: 2 }}>
        <Card><CardContent sx={{ py: 1.5, pr: { xs: 2, sm: 10 }, "&:last-child": { pb: 1.5 } }}>
          <Stack direction="row" spacing={1}>
            <Button onClick={add}>{t("exitq.set.add")}</Button>
            <Box sx={{ flex: 1 }} />
            <Button variant="contained" onClick={save} disabled={cfg.questions.some((q) => !(q.label.en ?? "").trim())}>{t("exitq.set.save")}</Button>
          </Stack>
        </CardContent></Card>
      </Box>
      <Typography sx={{ fontSize: 12, color: f.muted }}>{t("exitq.set.frozen")}</Typography>
    </Stack>
  );
}
