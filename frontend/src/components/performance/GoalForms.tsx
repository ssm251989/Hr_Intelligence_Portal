import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { performanceExtraApi, type GoalNode } from "../../api/performanceExtra";
import { useT } from "../../i18n";
import { Emoji, InfoTip, explainError } from "../../ui-kit";
import { ConfidencePicker, useFresh } from "./shared";

// F2: the quick monthly check-in -- pick a goal, drag the progress, say how sure you are.
export function CheckInForm({ goals, canEdit, onSaved }: { goals: Omit<GoalNode, "children">[]; canEdit: boolean; onSaved: () => void }) {
  const t = useT();
  const f = useFresh();
  const open = goals.filter((g) => g.status === "active");
  const firstDue = open.find((g) => g.checkin_due) ?? open[0];
  const [goalId, setGoalId] = useState(firstDue?.id ?? "");
  const goal = open.find((g) => g.id === goalId);
  const [progress, setProgress] = useState<number>(goal?.progress_pct ?? 0);
  const [confidence, setConfidence] = useState<number | null>(goal?.confidence ?? null);
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (!goalId && firstDue) setGoalId(firstDue.id);
  }, [firstDue, goalId]);
  useEffect(() => {
    setProgress(goal?.progress_pct ?? 0);
    setConfidence(goal?.confidence ?? null);
  }, [goal?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!open.length) {
    return <Typography sx={{ color: f.muted }}>{t("performance.checkin.no_goals")}</Typography>;
  }
  const save = async () => {
    if (!goal) return;
    setSaving(true);
    setMsg(null);
    try {
      await performanceExtraApi.checkIn(goal.id, { progress_pct: progress, confidence, comment: comment.trim() || null });
      setMsg({ ok: true, text: t("performance.checkin.saved", { title: goal.title, pct: progress }) });
      setComment("");
      onSaved();
    } catch (err) {
      const e = explainError(err);
      setMsg({ ok: false, text: `${e.what} ${e.fix}` });
    } finally {
      setSaving(false);
    }
  };
  return (
    <Stack spacing={2}>
      <TextField select label={t("performance.checkin.goal")} value={goalId} onChange={(e) => setGoalId(e.target.value)} size="small" helperText={t("performance.checkin.goal_hint")}>
        {open.map((g) => (
          <MenuItem key={g.id} value={g.id}>{g.checkin_due ? "⏰ " : ""}{g.title}</MenuItem>
        ))}
      </TextField>
      <Box>
        <Typography id="checkin-progress" sx={{ fontWeight: 700, fontSize: 14 }}>
          {t("performance.checkin.progress", { pct: progress })}
        </Typography>
        <Slider
          aria-labelledby="checkin-progress"
          value={progress}
          onChange={(_, v) => setProgress(v as number)}
          step={5}
          min={0}
          max={100}
          marks={[{ value: 0, label: "0%" }, { value: 50, label: "50%" }, { value: 100, label: "100%" }]}
          valueLabelDisplay="auto"
          valueLabelFormat={(v) => `${v}%`}
          disabled={!canEdit}
        />
      </Box>
      <Box>
        <Typography sx={{ fontWeight: 700, fontSize: 14, mb: 0.75 }}>
          {t("performance.checkin.confidence")}
          <InfoTip text={t("performance.checkin.confidence_tip")} />
        </Typography>
        <ConfidencePicker value={confidence} onChange={setConfidence} disabled={!canEdit} />
      </Box>
      <TextField
        label={t("performance.checkin.comment")}
        placeholder={t("performance.checkin.comment_placeholder")}
        helperText={t("performance.checkin.comment_hint")}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        multiline
        minRows={2}
        size="small"
        disabled={!canEdit}
      />
      {msg && <Alert severity={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
      {canEdit ? (
        <Button variant="contained" onClick={save} disabled={saving || !goal} startIcon={<Emoji name="check" size={16} />}>
          {saving ? t("performance.checkin.saving") : t("performance.checkin.save")}
        </Button>
      ) : (
        <Alert severity="info" icon={<Emoji name="lock" size={18} />}>{t("performance.checkin.no_edit")}</Alert>
      )}
    </Stack>
  );
}

const LEVELS = ["company", "department", "team", "individual"] as const;

export function AddGoalDialog({
  open, onClose, onSaved, parents, myEmployeeId,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  parents: GoalNode[];
  myEmployeeId: string | null;
}) {
  const t = useT();
  const [title, setTitle] = useState("");
  const [level, setLevel] = useState<string>(myEmployeeId ? "individual" : "team");
  const [parent, setParent] = useState("");
  const [weightage, setWeightage] = useState("");
  const [due, setDue] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const order = (l: string) => LEVELS.indexOf(l as (typeof LEVELS)[number]);
  const allowedParents = parents.filter((p) => order(p.level) <= order(level) && p.level !== "individual");

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await performanceExtraApi.createGoal({
        title: title.trim(), level, parent_goal_id: parent || null, owner_employee_id: level === "individual" ? myEmployeeId : null,
        weightage: weightage ? Number(weightage) : 0, due_date: due || null, description: description.trim() || undefined,
      });
      setTitle("");
      setDescription("");
      setWeightage("");
      setDue("");
      setParent("");
      onSaved();
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
      <DialogTitle>{t("performance.goal.add_title")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label={t("performance.goal.title")}
            placeholder={t("performance.goal.title_placeholder")}
            helperText={t("performance.goal.title_hint")}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            autoFocus
          />
          <TextField select label={t("performance.goal.level")} value={level} onChange={(e) => setLevel(e.target.value)} helperText={t("performance.goal.level_hint")}>
            {LEVELS.filter((l) => l !== "individual" || myEmployeeId).map((l) => (
              <MenuItem key={l} value={l}>{l === "individual" ? t("performance.level.me") : t(`performance.level.${l}`)}</MenuItem>
            ))}
          </TextField>
          <TextField select label={t("performance.goal.parent")} value={parent} onChange={(e) => setParent(e.target.value)} helperText={t("performance.goal.parent_hint")}>
            <MenuItem value="">{t("performance.goal.no_parent")}</MenuItem>
            {allowedParents.map((p) => (
              <MenuItem key={p.id} value={p.id}>{t(`performance.level.${p.level}`)} · {p.title}</MenuItem>
            ))}
          </TextField>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField
              label={t("performance.goal.weightage")}
              placeholder="25"
              helperText={t("performance.goal.weightage_hint")}
              type="number"
              value={weightage}
              onChange={(e) => setWeightage(e.target.value)}
              slotProps={{ htmlInput: { min: 0, max: 100 }, input: { endAdornment: <InfoTip text={t("performance.goal.weightage_tip")} /> } }}
              fullWidth
            />
            <TextField
              label={t("performance.goal.due")}
              type="date"
              value={due}
              onChange={(e) => setDue(e.target.value)}
              helperText={t("performance.goal.due_hint")}
              slotProps={{ inputLabel: { shrink: true } }}
              fullWidth
            />
          </Stack>
          <TextField
            label={t("performance.goal.description")}
            placeholder={t("performance.goal.description_placeholder")}
            helperText={t("performance.goal.description_hint")}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            multiline
            minRows={2}
          />
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={saving || !title.trim()}>
          {saving ? t("performance.goal.saving") : t("performance.goal.save")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
