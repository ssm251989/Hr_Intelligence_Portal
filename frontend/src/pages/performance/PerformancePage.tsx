import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link as RouterLink } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { performanceExtraApi, type MyPerformance } from "../../api/performanceExtra";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import GoalTree, { flattenGoals } from "../../components/performance/GoalTree";
import { AddGoalDialog, CheckInForm } from "../../components/performance/GoalForms";
import { NoAccess, Panel, PerfChip, useDateFormat, useFresh } from "../../components/performance/shared";
import { useT } from "../../i18n";
import { Cell, EmptyState, Emoji, FriendlyError, PageGrid, PageHeader, StatTile } from "../../ui-kit";

// Part 15.6 (spec L F1, F2): my goals as a tree (company > team > me), the monthly
// check-in nudge + quick check-in, and the reviews I still have to write.
export default function PerformancePage() {
  const t = useT();
  const f = useFresh();
  const date = useDateFormat();
  const { can, loading: bootLoading } = useMeBootstrap();
  const [data, setData] = useState<MyPerformance | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);

  const allowed = can("performance.self.view");
  const canCheckIn = can("performance.goal.edit");
  const canAddGoal = can("performance.goal.create");

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    performanceExtraApi
      .me()
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (allowed) load();
  }, [allowed, load]);

  if (bootLoading) return null;

  const header = (primary?: ReactNode) => (
    <PageHeader emoji="target" title={t("performance.title")} purpose={t("performance.purpose")} tourKey="performance" primary={primary}
      extra={can("performance.goal.view") ? <Button variant="outlined" component={RouterLink} to="/performance/team">{t("performance.team_link")}</Button> : undefined}
    />
  );

  if (!allowed) {
    return (
      <Box>
        {header()}
        <NoAccess what={t("performance.title")} />
      </Box>
    );
  }

  const mine = data?.my_goals ?? [];
  const avg = mine.length ? Math.round(mine.reduce((s, g) => s + g.progress_pct, 0) / mine.length) : 0;
  const toWrite = data?.reviews_to_write ?? [];
  const primary = canCheckIn && mine.length ? (
    <Button variant="contained" href="#checkin" startIcon={<Emoji name="memo" size={16} />}>{t("performance.primary_checkin")}</Button>
  ) : canAddGoal ? (
    <Button variant="contained" onClick={() => setAddOpen(true)} startIcon={<Emoji name="target" size={16} />}>{t("performance.goal.add")}</Button>
  ) : undefined;

  return (
    <Box>
      {header(primary)}

      {error ? (
        <FriendlyError error={error} onRetry={load} />
      ) : (
        <>
          {data && !data.employee && (
            <Card sx={{ p: 2, mb: 2.25, bgcolor: f.sunSoft, boxShadow: "none" }} role="status">
              <Stack direction="row" spacing={1.5} alignItems="center">
                <Emoji name="id_card" size={24} />
                <Typography>{t("performance.not_linked")}</Typography>
              </Stack>
            </Card>
          )}

          {data && data.checkin_due_count > 0 && (
            <Card sx={{ p: 2, mb: 2.25, bgcolor: f.sunSoft, boxShadow: "none" }} role="status" data-tour="checkin-nudge">
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "flex-start", sm: "center" }}>
                <Emoji name="alarm_clock" size={28} />
                <Box sx={{ flex: 1 }}>
                  <Typography sx={{ fontWeight: 800 }}>{t("performance.nudge.title", { count: data.checkin_due_count })}</Typography>
                  <Typography sx={{ color: f.ink, opacity: 0.8 }}>{t("performance.nudge.body")}</Typography>
                </Box>
                <Button variant="contained" href="#checkin">{t("performance.nudge.action")}</Button>
              </Stack>
            </Card>
          )}

          <PageGrid sx={{ mb: 2.25 }}>
            <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="target" value={mine.length} label={t("performance.stat.goals", { count: mine.length })} loading={loading} /></Cell>
            <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="chart_up" value={`${avg}%`} label={t("performance.stat.avg")} tone="ok" loading={loading} /></Cell>
            <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="alarm_clock" value={data?.checkin_due_count ?? 0} label={t("performance.stat.checkins_due", { count: data?.checkin_due_count ?? 0 })} tone={data?.checkin_due_count ? "sun" : "ok"} loading={loading} /></Cell>
            <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="writing_hand" value={toWrite.length} label={t("performance.stat.reviews", { count: toWrite.length })} tone={toWrite.length ? "sky" : "ok"} loading={loading} /></Cell>
          </PageGrid>

          <PageGrid>
            <Cell span={{ xs: 12, lg: 8 }}>
              <Panel
                emoji="compass"
                title={t("performance.tree.title")}
                tip={t("performance.tree.tip")}
                dataTour="goal-tree"
                action={canAddGoal && canCheckIn && mine.length ? <Button size="small" onClick={() => setAddOpen(true)}>＋ {t("performance.goal.add")}</Button> : undefined}
              >
                {loading && !data ? (
                  <Typography sx={{ color: f.muted }}>{t("performance.loading")}</Typography>
                ) : data && data.tree.length ? (
                  <GoalTree roots={data.tree} />
                ) : (
                  <EmptyState
                    compact
                    illustration="goals"
                    title={t("performance.tree.empty")}
                    hint={t("performance.tree.empty_hint")}
                    action={canAddGoal ? <Button variant="contained" onClick={() => setAddOpen(true)}>＋ {t("performance.goal.add_first")}</Button> : undefined}
                  />
                )}
              </Panel>
            </Cell>
            <Cell span={{ xs: 12, lg: 4 }} sx={{ gap: 2.25, "& > *": { flex: "0 0 auto" } }}>
              <Box id="checkin" sx={{ scrollMarginTop: 80 }}>
                <Panel emoji="memo" title={t("performance.checkin.title")} tip={t("performance.checkin.tip")} dataTour="checkin">
                  {data && <CheckInForm goals={mine} canEdit={canCheckIn} onSaved={load} />}
                </Panel>
              </Box>
              <Panel emoji="writing_hand" title={t("performance.reviews.title")} dataTour="reviews">
                {toWrite.length === 0 ? (
                  <EmptyState compact illustration="done" title={t("performance.reviews.none")} />
                ) : (
                  <Stack spacing={1}>
                    {toWrite.map((r) => (
                      <Stack key={r.id} direction="row" spacing={1.25} alignItems="center" sx={{ p: 1.25, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                          <Typography sx={{ fontWeight: 700 }} noWrap>
                            {r.about_me ? t("performance.reviews.self") : t("performance.reviews.about", { name: r.employee_name || t("performance.someone") })}
                          </Typography>
                          <Typography sx={{ fontSize: 12, color: f.muted }}>
                            {r.cycle_name} · {t(`performance.stage.${r.stage}`)} · {t("performance.reviews.due", { date: date(r.due_date) })}
                          </Typography>
                        </Box>
                        <PerfChip status={r.status} />
                        <Button size="small" variant="outlined" component={RouterLink} to={`/performance/review/${r.id}`} disabled={!r.cycle_open}>
                          {r.status === "draft" ? t("performance.reviews.continue") : t("performance.reviews.start")}
                        </Button>
                      </Stack>
                    ))}
                  </Stack>
                )}
              </Panel>
            </Cell>
          </PageGrid>
        </>
      )}

      <AddGoalDialog open={addOpen} onClose={() => setAddOpen(false)} onSaved={load} parents={flattenGoals(data?.tree ?? [])} myEmployeeId={data?.employee?.id ?? null} />
    </Box>
  );
}
