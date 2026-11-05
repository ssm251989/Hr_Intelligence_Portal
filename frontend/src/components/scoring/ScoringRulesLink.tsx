import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { screeningApi } from "../../api/client";
import { useT } from "../../i18n";
import { Emoji } from "../../ui-kit";

// Part 18.10: list pages only FILTER. The shortlist score and all weights are set in one
// place -- Settings > Hiring > Scoring rules (company default + per-job override) -- so the
// pages show the current company score read-only with a link there.
export default function ScoringRulesLink() {
  const t = useT();
  const [score, setScore] = useState<number | null>(null);
  useEffect(() => {
    screeningApi.getSettings().then((s) => setScore(Math.round(Number(s.shortlist_threshold)))).catch(() => setScore(null));
  }, []);
  return (
    <Card sx={{ p: 1.5, mb: 2 }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
        <Emoji name="target" size={22} />
        <Typography sx={{ flex: 1 }}>
          {score != null ? t("scoringlink.text", { score }) : t("scoringlink.text_no_score")}
        </Typography>
        <Button size="small" variant="outlined" component={RouterLink} to="/settings/hiring/scoring">{t("scoringlink.open")}</Button>
      </Stack>
    </Card>
  );
}
