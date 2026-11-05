import { useState, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { useAutosaveDraft } from "../hooks/useAutosaveDraft";
import Emoji from "./Emoji";

export interface FormStep<T> {
  key: string;
  emoji: string;
  title: string;
  /** One line telling the user what this step is for. */
  hint?: string;
  render: (value: T, set: (patch: Partial<T>) => void) => ReactNode;
  /** Return a plain-language problem to block "Next", or null when the step is fine. */
  validate?: (value: T) => string | null;
}

// Part 15 C: long forms become steps with a progress bar and autosave (server-side draft,
// so it follows the user across devices -- Part 14 useAutosaveDraft).
export default function StepForm<T extends Record<string, unknown>>({
  formKey, entityRef = "", steps, initial, onSubmit, submitLabel = "Finish",
}: {
  formKey: string;
  entityRef?: string;
  steps: FormStep<T>[];
  initial: T;
  onSubmit: (value: T) => Promise<void> | void;
  submitLabel?: string;
}) {
  const t = useTheme().palette.fresh;
  const [value, setValue] = useState<T>(initial);
  const [index, setIndex] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { savedAt, restored, clear } = useAutosaveDraft<T>(formKey, entityRef, value, setValue);

  const step = steps[index];
  const set = (patch: Partial<T>) => setValue((v) => ({ ...v, ...patch }));
  const pct = Math.round(((index + 1) / steps.length) * 100);
  const last = index === steps.length - 1;

  const next = async () => {
    const issue = step.validate?.(value) ?? null;
    setProblem(issue);
    if (issue) return;
    if (!last) {
      setIndex(index + 1);
      return;
    }
    setBusy(true);
    try {
      await onSubmit(value);
      await clear().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Typography sx={{ fontWeight: 700 }}>Step {index + 1} of {steps.length}</Typography>
        <Typography sx={{ fontSize: 12, color: t.muted }} aria-live="polite">
          {savedAt ? `Saved ${new Date(savedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : restored ? "Draft restored" : "Saves as you type"}
        </Typography>
      </Stack>
      <LinearProgress variant="determinate" value={pct} aria-label={`${pct}% done`} />
      <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: "wrap", rowGap: 1 }} role="list" aria-label="Steps">
        {steps.map((s, i) => (
          <Box key={s.key} role="listitem" aria-current={i === index ? "step" : undefined}
            sx={{ display: "inline-flex", alignItems: "center", gap: 0.75, px: 1.25, py: 0.5, borderRadius: 999, fontSize: 12, fontWeight: 700,
              bgcolor: i === index ? t.brandSoft : i < index ? t.okSoft : t.surface2, color: i === index ? t.brand : i < index ? t.ok : t.muted }}>
            <Emoji name={i < index ? "check" : s.emoji} size={14} />{s.title}
          </Box>
        ))}
      </Stack>
      <Box sx={{ mt: 3 }}>
        <Typography variant="h5" component="h2">{step.title}</Typography>
        {step.hint && <Typography sx={{ color: t.muted, mt: 0.5 }}>{step.hint}</Typography>}
        <Box sx={{ mt: 2.5 }}>{step.render(value, set)}</Box>
        {problem && <Typography role="alert" sx={{ mt: 2, color: t.coral, fontWeight: 600 }}>{problem}</Typography>}
      </Box>
      <Stack direction="row" spacing={1} justifyContent="flex-end" sx={{ mt: 3 }}>
        {index > 0 && <Button variant="outlined" onClick={() => setIndex(index - 1)}>Back</Button>}
        <Button variant="contained" onClick={next} disabled={busy}>{last ? submitLabel : "Next"}</Button>
      </Stack>
    </Card>
  );
}
