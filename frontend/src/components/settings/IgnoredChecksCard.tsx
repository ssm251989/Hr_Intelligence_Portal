import { useEffect, useState } from "react";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { experienceApi, type HealthIssue } from "../../api/client";
import { useT } from "../../i18n";

// Fix 2026-10-05: Settings > Data & privacy > System health -- the configuration-health checks an
// admin hid with "Ignore this" on the home page, each with "Show again".
export default function IgnoredChecksCard() {
  const t = useT();
  const [ignored, setIgnored] = useState<HealthIssue[] | null>(null);
  useEffect(() => { experienceApi.configHealth().then((r) => setIgnored(r.ignored ?? [])).catch(() => setIgnored([])); }, []);
  const undo = async (key: string) => setIgnored((await experienceApi.configHealthIgnore(key, false)).ignored ?? []);
  if (ignored === null) return null;
  return (
    <Card data-testid="ignored-checks">
      <CardContent>
        <Typography sx={{ fontWeight: 800 }}>{t("health.ignored.title", { n: ignored.length })}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{t("health.ignored.intro")}</Typography>
        {ignored.length === 0 && <Typography variant="body2" color="text.secondary">{t("health.ignored.none")}</Typography>}
        <Stack spacing={1}>
          {ignored.map((i) => (
            <Stack key={i.key} direction="row" spacing={1} alignItems="center" justifyContent="space-between">
              <Typography variant="body2">{i.message}</Typography>
              <Button size="small" variant="outlined" onClick={() => undo(i.key as string)}>{t("health.unignore")}</Button>
            </Stack>
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
}
