import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { useT } from "../../i18n";
import { Emoji, InfoTip } from "../../ui-kit";
import JdPreview from "./JdPreview";

// J3: the job description in a side-by-side editor -- left: what the AI will use + the
// text you edit; right: the live preview candidates will see. AI affordances only render
// when the company has JD drafting switched on (`aiEnabled`, from useMeBootstrap().aiFeature).
export default function JdSideBySide({
  value, onChange, aiEnabled, generating, onGenerate, inputs,
}: {
  value: string;
  onChange: (next: string) => void;
  aiEnabled: boolean;
  generating: boolean;
  /** Resolves with the AI text once the server has written it. */
  onGenerate: () => Promise<string | null>;
  /** Short chips of what the AI draws on (title, skills, pay...). */
  inputs: string[];
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [before, setBefore] = useState<string | null>(null);

  const generate = async () => {
    const previous = value;
    const next = await onGenerate();
    if (next !== null) setBefore(previous.trim() ? previous : null);
  };

  return (
    <Grid container spacing={2.5}>
      <Grid size={{ xs: 12, md: 6 }}>
        <Stack spacing={1.5}>
          {aiEnabled && (
            <Card sx={{ p: 2, bgcolor: f.brandSoft, boxShadow: "none" }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <Emoji name="sparkles" size={20} />
                <Typography sx={{ fontWeight: 700 }}>{t("jobs.jd.uses")}</Typography>
                <InfoTip text={t("jobs.jd.ai_hint")} />
              </Stack>
              <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
                {inputs.map((chip) => (
                  <Box key={chip} component="span" sx={{ fontSize: 12, fontWeight: 600, px: 1, py: 0.25, borderRadius: 999, bgcolor: f.surface, border: `1px solid ${f.line}` }}>
                    {chip}
                  </Box>
                ))}
              </Stack>
              <Button variant="contained" onClick={generate} disabled={generating} startIcon={<Emoji name="magic" size={18} />}>
                {generating ? t("jobs.jd.ai_busy") : t("jobs.jd.ai")}
              </Button>
            </Card>
          )}
          {before !== null && (
            <Stack direction="row" spacing={1} alignItems="center" role="status" sx={{ p: 1.25, borderRadius: "12px", bgcolor: f.skySoft }}>
              <Typography variant="body2" sx={{ flex: 1 }}>{t("jobs.jd.ai_done")}</Typography>
              <Button size="small" onClick={() => { onChange(before); setBefore(null); }}>{t("jobs.jd.undo")}</Button>
            </Stack>
          )}
          <TextField
            label={t("jobs.jd.editor")}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            multiline
            minRows={14}
            fullWidth
            slotProps={{ htmlInput: { "aria-describedby": "jd-preview-heading" } }}
          />
        </Stack>
      </Grid>
      <Grid size={{ xs: 12, md: 6 }}>
        <Card sx={{ p: 2.5, height: "100%", bgcolor: f.surface2, boxShadow: "none", border: `1px solid ${f.line}` }} aria-live="polite">
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
            <Emoji name="eyes" size={18} />
            <Typography id="jd-preview-heading" sx={{ fontWeight: 700, color: f.muted, fontSize: 13, textTransform: "uppercase", letterSpacing: ".06em" }}>
              {t("jobs.jd.preview")}
            </Typography>
          </Stack>
          <Box sx={{ maxHeight: 460, overflowY: "auto", pr: 1 }}>
            <JdPreview text={value} empty={t(aiEnabled ? "jobs.jd.preview_empty_ai" : "jobs.jd.preview_empty")} />
          </Box>
        </Card>
      </Grid>
    </Grid>
  );
}
