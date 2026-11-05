import Box from "@mui/material/Box";
import MenuItem from "@mui/material/MenuItem";
import Rating from "@mui/material/Rating";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import type { Answers, ExitQuestion } from "../../api/exitInterviewApi";
import { useI18n } from "../../i18n";

// fix 2026-10-06: the exit interview questions (from Settings) -- answered by the employee; HR sees the
// same layout READ-ONLY (and fills it only for "Record answers from a call").

export function useQuestionLabel() {
  const { locale } = useI18n();
  return (q: ExitQuestion) => q.label[locale as "en" | "hi" | "ta"] || q.label.en || q.id;
}

export function ExitInterviewFields({ questions, answers, onChange, readOnly }: {
  questions: ExitQuestion[]; answers: Answers; onChange?: (id: string, v: string | number | null) => void; readOnly?: boolean;
}) {
  const { t } = useI18n();
  const f = useTheme().palette.fresh;
  const label = useQuestionLabel();
  return (
    <Stack spacing={2}>
      {questions.map((q) => {
        const v = answers[q.id];
        const title = `${label(q)}${q.required && !readOnly ? " *" : ""}`;
        if (readOnly) {
          const shown = v === null || v === undefined || v === "" ? null
            : q.type === "stars" ? `${"★".repeat(Number(v))}${"☆".repeat(5 - Number(v))} (${v}/5)`
              : q.type === "yes_maybe_no" ? t(`exits.a.${v}`) : String(v);
          return (
            <Box key={q.id}>
              <Typography sx={{ fontSize: 13, color: f.muted }}>{label(q)}</Typography>
              <Typography sx={{ fontSize: 15, whiteSpace: "pre-wrap", fontStyle: shown ? "normal" : "italic", color: shown ? f.ink : f.muted }}>
                {shown ?? t("exitq.no_answer")}
              </Typography>
            </Box>
          );
        }
        if (q.type === "stars") {
          return (
            <Box key={q.id}>
              <Typography id={`eq-${q.id}`} sx={{ fontSize: 14, fontWeight: 600 }}>{title}</Typography>
              <Rating aria-labelledby={`eq-${q.id}`} value={Number(v) || null} onChange={(_, nv) => onChange?.(q.id, nv)} />
            </Box>
          );
        }
        if (q.type === "yes_maybe_no") {
          return (
            <Box key={q.id}>
              <Typography id={`eq-${q.id}`} sx={{ fontSize: 14, fontWeight: 600, mb: 0.5 }}>{title}</Typography>
              <ToggleButtonGroup exclusive size="small" aria-labelledby={`eq-${q.id}`} value={v ?? null} onChange={(_, nv) => onChange?.(q.id, nv)}>
                {(["yes", "maybe", "no"] as const).map((x) => <ToggleButton key={x} value={x}>{t(`exits.a.${x}`)}</ToggleButton>)}
              </ToggleButtonGroup>
            </Box>
          );
        }
        if (q.type === "choice") {
          return (
            <TextField key={q.id} select label={title} value={v ?? ""} onChange={(e) => onChange?.(q.id, e.target.value)} sx={{ maxWidth: 420 }}>
              <MenuItem value="">—</MenuItem>
              {(q.options ?? []).map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
            </TextField>
          );
        }
        return <TextField key={q.id} label={title} value={v ?? ""} onChange={(e) => onChange?.(q.id, e.target.value)} multiline minRows={2} fullWidth />;
      })}
    </Stack>
  );
}
