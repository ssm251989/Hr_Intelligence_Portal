// Part 17.12: /interviews/availability -- "My availability". The app is the only source of
// interviewer availability (no Excel): my weekly hours, blocked dates and limits, plus the
// interviews already booked for me (those times count as busy automatically).
import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { interviewersApi, type Availability, type AvailabilityIn } from "../../api/interviewersApi";
import AvailabilityEditor from "../../components/interviews/AvailabilityEditor";
import { Section } from "../../components/servicedesk/shared";
import { useT } from "../../i18n";
import { Cell, FriendlyError, PageGrid, PageHeader, StatusChip } from "../../ui-kit";

export default function MyAvailabilityPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [data, setData] = useState<Availability | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => { interviewersApi.me().then(setData).catch(setError); }, []);

  const save = async (payload: AvailabilityIn) => {
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      setData(await interviewersApi.saveMe(payload));
      setSaved(true);
    } catch (e) {
      setSaveError(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box>
      <PageHeader emoji="calendar" title={t("interviewers.my.title")} purpose={t("interviewers.my.purpose")} />
      {error ? <FriendlyError error={error} /> : !data ? <CircularProgress aria-label={t("interviewers.loading")} /> : (
        <PageGrid>
          <Cell span={{ md: 12, lg: 8 }}>
            <Section emoji="alarm_clock" title={t("interviewers.my.hours")}>
              {data.suggested && <Alert severity="info" sx={{ mb: 2 }}>{t("interviewers.my.suggested")}</Alert>}
              {saved && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaved(false)}>{t("interviewers.my.saved")}</Alert>}
              <AvailabilityEditor initial={data} onSave={save} saving={saving} error={saveError} />
            </Section>
          </Cell>
          <Cell span={{ md: 12, lg: 4 }}>
            <Section emoji="clipboard" title={t("interviewers.my.summary")}>
              <Stack spacing={1.5}>
                <Box>
                  <Typography sx={{ fontSize: 13, color: f.muted }}>{t("interviewers.my.free_tomorrow")}</Typography>
                  <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
                    {data.free_tomorrow.length ? data.free_tomorrow.map((s) => <StatusChip key={s} tone="ok" emoji="check" label={s} />)
                      : <StatusChip tone="muted" emoji="pause" label={t("interviewers.none_free")} />}
                  </Stack>
                </Box>
                <Typography sx={{ fontSize: 14 }}>{t("interviewers.my.booked", { count: data.booked_next_7_days })}</Typography>
                <Typography sx={{ fontSize: 14 }}>{t("interviewers.my.pools", { list: data.pools.join(", ") || t("interviewers.my.no_pools") })}</Typography>
                {(data.upcoming ?? []).length > 0 && (
                  <Box>
                    <Typography sx={{ fontWeight: 700, fontSize: 14 }}>{t("interviewers.my.upcoming")}</Typography>
                    {(data.upcoming ?? []).slice(0, 8).map((u) => (
                      <Typography key={u.id} sx={{ fontSize: 13, color: f.muted }}>{new Date(u.scheduled_at).toLocaleString()}</Typography>
                    ))}
                  </Box>
                )}
              </Stack>
            </Section>
          </Cell>
        </PageGrid>
      )}
    </Box>
  );
}
