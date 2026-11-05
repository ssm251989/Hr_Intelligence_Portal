import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tabs from "@mui/material/Tabs";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";

import { performanceExtraApi, type NineBox, type TeamMember, type TeamView } from "../../api/performanceExtra";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import NineBoxBoard from "../../components/performance/NineBoxBoard";
import { NoAccess, PerfChip, ProgressBar, useDateFormat, useFresh } from "../../components/performance/shared";
import { useT } from "../../i18n";
import { Cell, EmptyState, Emoji, FriendlyError, InfoTip, PageGrid, PageHeader, StatTile, UserAvatar, explainError } from "../../ui-kit";

// Part 15.6 (spec L F5, F6): a manager's table of every reportee + the 9-box board.
// A 9-box move is saved on the person's talent profile (PATCH /talent/{id}, kept next to
// their other mobility notes).

export default function TeamPerformancePage() {
  const t = useT();
  const f = useFresh();
  const date = useDateFormat();
  const { can, loading: bootLoading } = useMeBootstrap();
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [tab, setTab] = useState<"table" | "ninebox">("table");
  const [data, setData] = useState<TeamView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);
  const allowed = can("performance.goal.view");

  const load = useCallback((s: "mine" | "all") => {
    setLoading(true);
    setError(null);
    performanceExtraApi
      .team(s)
      .then((d) => {
        setData(d);
        // No direct reports but allowed to see more: start with everyone.
        if (s === "mine" && !d.has_team && d.can_see_all) {
          setScope("all");
        }
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (allowed) load(scope);
  }, [allowed, scope, load]);

  const place = async (person: TeamMember, box: NineBox | null) => {
    if (!data) return;
    const before = data.people;
    setData({ ...data, people: data.people.map((p) => (p.employee_id === person.employee_id ? { ...p, nine_box: box } : p)) });
    setSavingId(person.employee_id);
    try {
      const profile = await performanceExtraApi.talent(person.employee_id);
      const mobility = { ...(profile.mobility ?? {}) } as Record<string, unknown>;
      if (box) mobility.nine_box = { ...box, placed_at: new Date().toISOString() };
      else delete mobility.nine_box;
      await performanceExtraApi.patchTalent(person.employee_id, { mobility_json: mobility });
      setToast({ ok: true, text: box ? t("performance.ninebox.saved", { name: person.name, box: t(`performance.ninebox.box.${box.performance}x${box.potential}`) }) : t("performance.ninebox.removed", { name: person.name }) });
    } catch (err) {
      setData((d) => (d ? { ...d, people: before } : d));
      const e = explainError(err);
      setToast({ ok: false, text: `${e.what} ${e.fix}` });
    } finally {
      setSavingId(null);
    }
  };

  if (bootLoading) return null;
  const header = (
    <PageHeader
      emoji="people"
      title={t("performance.team.title")}
      purpose={t("performance.team.purpose")}
      tourKey="performance-team"
      extra={<Button variant="text" component={RouterLink} to="/performance">{t("performance.team.back")}</Button>}
      primary={data?.show_talent ? <Button variant="contained" onClick={() => setTab("ninebox")} startIcon={<Emoji name="target" size={16} />}>{t("performance.team.open_ninebox")}</Button> : undefined}
    />
  );
  if (!allowed) {
    return (
      <Box>
        {header}
        <NoAccess what={t("performance.team.title")} />
      </Box>
    );
  }

  const people = data?.people ?? [];
  const due = people.filter((p) => p.checkin_due).length;
  const reviewsOpen = people.filter((p) => p.review_status && p.review_status !== "submitted").length;
  const avg = people.filter((p) => p.avg_progress != null);
  const avgProgress = avg.length ? Math.round(avg.reduce((s, p) => s + (p.avg_progress ?? 0), 0) / avg.length) : 0;

  return (
    <Box>
      {header}
      {error ? (
        <FriendlyError error={error} onRetry={() => load(scope)} />
      ) : (
        <>
          <PageGrid sx={{ mb: 2.25 }}>
            <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="people" value={people.length} label={t("performance.team.stat.people", { count: people.length })} loading={loading} /></Cell>
            <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="chart_up" value={`${avgProgress}%`} label={t("performance.team.stat.progress")} tone="ok" loading={loading} /></Cell>
            <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="alarm_clock" value={due} label={t("performance.team.stat.checkins", { count: due })} tone={due ? "sun" : "ok"} loading={loading} /></Cell>
            <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="writing_hand" value={reviewsOpen} label={t("performance.team.stat.reviews", { count: reviewsOpen })} tone={reviewsOpen ? "sky" : "ok"} loading={loading} /></Cell>
          </PageGrid>

          <Card sx={{ p: { xs: 1.5, md: 2.5 } }}>
            <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ xs: "flex-start", md: "center" }} sx={{ mb: 2 }}>
              <Tabs value={tab} onChange={(_, v) => setTab(v)} aria-label={t("performance.team.tabs")} sx={{ flex: 1 }}>
                <Tab value="table" label={t("performance.team.tab_table")} />
                <Tab value="ninebox" label={<Stack direction="row" spacing={0.5} alignItems="center"><span>{t("performance.team.tab_ninebox")}</span></Stack>} />
              </Tabs>
              {data?.can_see_all && (
                <ToggleButtonGroup size="small" exclusive value={scope} onChange={(_, v) => v && setScope(v)} aria-label={t("performance.team.scope")}>
                  <ToggleButton value="mine" disabled={!data.has_team}>{t("performance.team.scope_mine")}</ToggleButton>
                  <ToggleButton value="all">{t("performance.team.scope_all")}</ToggleButton>
                </ToggleButtonGroup>
              )}
            </Stack>

            {!loading && people.length === 0 ? (
              <EmptyState illustration="team-spirit" title={t("performance.team.empty")} hint={t("performance.team.empty_hint")} />
            ) : tab === "table" ? (
              <TableContainer>
                <Table size="small" aria-label={t("performance.team.title")}>
                  <TableHead>
                    <TableRow>
                      <TableCell>{t("performance.team.col.person")}</TableCell>
                      <TableCell>{t("performance.team.col.goals")}</TableCell>
                      <TableCell>{t("performance.team.col.progress")}</TableCell>
                      <TableCell>{t("performance.team.col.checkin")}</TableCell>
                      <TableCell>{t("performance.team.col.review")}{data?.cycle ? ` · ${data.cycle.name}` : ""}</TableCell>
                      <TableCell>{t("performance.team.col.rating")}</TableCell>
                      {data?.show_talent && <TableCell>{t("performance.team.col.ninebox")}<InfoTip text={t("performance.ninebox.tip")} /></TableCell>}
                      <TableCell align="right">{t("performance.team.col.action")}</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {people.map((p) => (
                      <TableRow key={p.employee_id} hover>
                        <TableCell>
                          <Stack direction="row" spacing={1.25} alignItems="center">
                            <UserAvatar name={p.name} size={34} />
                            <Box sx={{ minWidth: 0 }}>
                              <Typography sx={{ fontWeight: 700 }} noWrap>{p.name}</Typography>
                              <Typography sx={{ fontSize: 12, color: f.muted }} noWrap>{[p.designation, p.department].filter(Boolean).join(" · ") || "—"}</Typography>
                            </Box>
                          </Stack>
                        </TableCell>
                        <TableCell>{t("performance.team.goals_count", { count: p.goals })}</TableCell>
                        <TableCell sx={{ minWidth: 180 }}>{p.avg_progress != null ? <ProgressBar value={p.avg_progress} compact /> : <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("performance.team.no_goals")}</Typography>}</TableCell>
                        <TableCell>
                          {p.goals === 0 ? "—" : p.checkin_due ? <PerfChip status="checkin_due" /> : <PerfChip status="checkin_ok" label={t("performance.team.checked_in", { date: date(p.last_checkin_at) })} />}
                        </TableCell>
                        <TableCell>{p.review_status ? <PerfChip status={p.review_status} /> : <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("performance.team.no_review")}</Typography>}</TableCell>
                        <TableCell sx={{ fontVariantNumeric: "tabular-nums" }}>{p.rating != null ? t("performance.team.rating_words", { rating: p.rating }) : "—"}</TableCell>
                        {data?.show_talent && (
                          <TableCell>{p.nine_box ? t(`performance.ninebox.box.${p.nine_box.performance}x${p.nine_box.potential}`) : <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("performance.ninebox.not_placed")}</Typography>}</TableCell>
                        )}
                        <TableCell align="right">
                          {p.manager_review_id ? (
                            <Button size="small" variant="outlined" component={RouterLink} to={`/performance/review/${p.manager_review_id}`}>
                              {p.review_status === "submitted" ? t("performance.team.view_review") : t("performance.team.write_review")}
                            </Button>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            ) : !data?.show_talent ? (
              <Alert severity="info" icon={<Emoji name="lock" size={18} />}>{t("performance.ninebox.no_access")}</Alert>
            ) : (
              <Box>
                <Typography sx={{ color: f.muted, mb: 1.5 }}>
                  {data.can_edit_talent ? t("performance.ninebox.howto") : t("performance.ninebox.readonly")}
                  <InfoTip text={t("performance.ninebox.tip")} />
                </Typography>
                <NineBoxBoard people={people} canEdit={data.can_edit_talent} onPlace={place} savingId={savingId} />
              </Box>
            )}
          </Card>
        </>
      )}
      <Snackbar open={Boolean(toast)} autoHideDuration={5000} onClose={() => setToast(null)} anchorOrigin={{ vertical: "bottom", horizontal: "center" }}>
        <Alert severity={toast?.ok ? "success" : "error"} onClose={() => setToast(null)}>{toast?.text}</Alert>
      </Snackbar>
    </Box>
  );
}
