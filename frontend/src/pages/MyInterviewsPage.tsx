import { useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Collapse from "@mui/material/Collapse";
import Grid from "@mui/material/Grid";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { ApiError, candidatesApi, extractErrorMessage, schedulingApi } from "../api/client";
import { interviewsExtraApi, type MyInterviewRow } from "../api/interviewsExtra";
import { useAuth } from "../auth/AuthContext";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";
import InterviewWeekCalendar from "../components/interviews/InterviewWeekCalendar";
import { startOfWeek } from "../components/interviews/weekDates";
import { openBlob } from "../api/selfServiceApi";
import Alert from "@mui/material/Alert";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import { InterviewStatusChip } from "../components/InterviewChips";
import RefreshButton from "../components/RefreshButton";
import ScorecardForm from "../components/interviews/ScorecardForm";
import { localeTag } from "../components/interviews/weekDates";
import { useI18n } from "../i18n";
import Emoji from "../ui-kit/Emoji";
import EmptyState from "../ui-kit/EmptyState";
import FriendlyError from "../ui-kit/FriendlyError";
import PageHeader from "../ui-kit/PageHeader";
import StatTile from "../ui-kit/StatTile";
import StatusChip from "../ui-kit/StatusChip";
import UserAvatar from "../ui-kit/UserAvatar";
import { useReducedMotion } from "../ui-kit/motion";

type TabKey = "upcoming" | "feedback" | "done";

// Spec I2: "My interviews" for the person doing the interviewing -- what's coming up, the
// join link, a short candidate summary, and the scorecard (with AI questions inside) right
// on the card. Data: GET /api/v1/ui/interviews/mine; if that isn't available it falls back
// to the Interview List filtered to the signed-in user.
export default function MyInterviewsPage() {
  const f = useTheme().palette.fresh;
  const { t, locale } = useI18n();
  const { user } = useAuth();
  const me = useMeBootstrap();
  // Part 20.4: every row here is the signed-in person's own interview -> they can always give feedback (the server checks it)
  const canWrite = true;
  const staff = me.can("recruitment.candidate.view");
  const [view, setView] = useState<"list" | "calendar">("list");
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()));
  const [answer, setAnswer] = useState<{ row: MyInterviewRow; kind: "declined" | "reschedule" } | null>(null);
  const reduced = useReducedMotion();
  const [rows, setRows] = useState<MyInterviewRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<TabKey>("upcoming");
  const [openId, setOpenId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    interviewsExtraApi
      .mine(true)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404 && user) {
          return schedulingApi.listAll({ interviewerId: user.id, pageSize: 200 }).then((page) =>
            page.items.map<MyInterviewRow>((interview) => ({
              interview,
              top_skills: [],
              missing_skills: [],
              feedback_submitted: interview.status === "selected" || interview.status === "rejected",
            })),
          );
        }
        throw err;
      })
      .then(setRows)
      .catch(setError)
      .finally(() => setLoading(false));
  };

  useEffect(load, [user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const groups = useMemo(() => {
    const upcoming = rows.filter((r) => r.interview.status === "upcoming").sort((a, b) => (a.interview.scheduled_at ?? "").localeCompare(b.interview.scheduled_at ?? ""));
    const feedback = rows.filter((r) => r.interview.status === "awaiting_feedback" && !r.feedback_submitted);
    const done = rows.filter((r) => !upcoming.includes(r) && !feedback.includes(r)).reverse();
    return { upcoming, feedback, done };
  }, [rows]);

  const next = groups.upcoming[0];
  const nextJoin = next ? next.interview.meeting_link || next.interview.calendar_link : null;
  const fmt = new Intl.DateTimeFormat(localeTag(locale), { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  const list = groups[tab];

  return (
    <Box>
      <PageHeader
        emoji="calendar"
        title={t("interviews.my.title")}
        purpose={t("interviews.my.purpose")}
        tourKey="interviews"
        extra={<Stack direction="row" spacing={1}><Button component={RouterLink} to="/interviews/availability" startIcon={<Emoji name="calendar" size={16} />}>{t("iv20.my_availability")}</Button><RefreshButton loading={loading} onRefresh={load} /></Stack>}
        primary={
          nextJoin ? (
            <Button variant="contained" component="a" href={nextJoin} target="_blank" rel="noopener noreferrer" startIcon={<Emoji name="link" size={18} />}>
              {t("interviews.my.join_next")}
            </Button>
          ) : undefined
        }
      />

      <Grid container spacing={2} sx={{ mb: 2.5 }}>
        <Grid size={{ xs: 12, sm: 4 }}>
          <StatTile emoji="calendar" tone="sky" value={groups.upcoming.length} label={t("interviews.my.tile_upcoming")} loading={loading} />
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <StatTile emoji="alarm_clock" tone={groups.feedback.length ? "sun" : "ok"} value={groups.feedback.length} label={t("interviews.my.tile_feedback")} loading={loading} />
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <StatTile emoji="check" tone="ok" value={groups.done.length} label={t("interviews.my.tile_done")} loading={loading} />
        </Grid>
      </Grid>

      <ToggleButtonGroup exclusive size="small" value={view} onChange={(_e, v) => v && setView(v)} sx={{ mb: 1.5 }} aria-label={t("iv20.view")}>
        <ToggleButton value="list">{t("iv20.view_list")}</ToggleButton>
        <ToggleButton value="calendar">{t("iv20.view_calendar")}</ToggleButton>
      </ToggleButtonGroup>
      {view === "calendar" && (
        <Box sx={{ mb: 2 }} data-testid="my-interviews-calendar">
          <InterviewWeekCalendar weekStart={weekStart} onWeekChange={setWeekStart} rows={rows.map((r) => r.interview)} loading={loading}
            onOpen={(row) => {
              const r = rows.find((x) => x.interview.interview_id === row.interview_id);
              if (r) { setView("list"); setTab(groups.upcoming.includes(r) ? "upcoming" : groups.feedback.includes(r) ? "feedback" : "done"); }
            }} />
        </Box>
      )}
      <Tabs value={tab} onChange={(_e, v: TabKey) => setTab(v)} sx={{ mb: 2 }} aria-label={t("interviews.my.tabs")}>
        <Tab value="upcoming" label={t("interviews.my.tab_upcoming", { count: groups.upcoming.length })} />
        <Tab value="feedback" label={t("interviews.my.tab_feedback", { count: groups.feedback.length })} />
        <Tab value="done" label={t("interviews.my.tab_done", { count: groups.done.length })} />
      </Tabs>

      {error ? (
        <FriendlyError error={error} onRetry={load} />
      ) : loading ? (
        <Stack spacing={2}>
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} variant="rounded" height={140} sx={{ borderRadius: "18px" }} />
          ))}
        </Stack>
      ) : list.length === 0 ? (
        <Card>
          <EmptyState
            illustration={tab === "feedback" ? "done" : "calendar"}
            title={t(`interviews.my.empty_${tab}`)}
            action={staff ? (
              <Button variant="outlined" component={RouterLink} to="/interviews/list">
                {t("interviews.my.see_all")}
              </Button>
            ) : undefined}
          />
        </Card>
      ) : (
        <Stack spacing={2}>
          {list.map((r) => {
            const iv = r.interview;
            const name = iv.candidate_name || t("interviews.unnamed");
            const join = iv.meeting_link || iv.calendar_link;
            const isOpen = openId === iv.interview_id;
            const facts = [
              r.total_experience_years != null ? t("interviews.my.experience", { count: r.total_experience_years }) : null,
              r.candidate_location || null,
              (r.composite_score ?? r.match_score) != null
                ? t("interviews.my.match", { value: Math.round((r.composite_score ?? r.match_score) as number) })
                : null,
            ].filter(Boolean) as string[];
            return (
              <Card key={iv.interview_id} component="article" aria-label={t("interviews.my.card_label", { name })} sx={{ p: 2.25 }}>
                <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ xs: "flex-start", md: "center" }} justifyContent="space-between">
                  <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minWidth: 0 }}>
                    <UserAvatar name={name} size={48} />
                    <Box sx={{ minWidth: 0 }}>
                      <Typography sx={{ fontWeight: 800, fontSize: 16 }}>{name}</Typography>
                      <Typography sx={{ color: f.muted, fontSize: 13 }}>{iv.job_title}</Typography>
                      {facts.length > 0 && <Typography sx={{ color: f.muted, fontSize: 13 }}>{facts.join(" · ")}</Typography>}
                    </Box>
                  </Stack>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <StatusChip tone="muted" emoji="alarm_clock" label={iv.scheduled_at ? fmt.format(new Date(iv.scheduled_at)) : t("interviews.no_time")} />
                    <InterviewStatusChip status={iv.status} />
                    {r.feedback_submitted && <StatusChip tone="ok" emoji="check" label={t("interviews.my.feedback_sent")} />}
                    {r.interviewer_response && (
                      <StatusChip tone={r.interviewer_response.kind === "declined" ? "coral" : "sun"} emoji="hourglass"
                        label={t(r.interviewer_response.kind === "declined" ? "iv20.declined_chip" : "iv20.proposed_chip", { when: r.interviewer_response.proposed ?? "" })} />
                    )}
                  </Stack>
                </Stack>

                {(r.top_skills.length > 0 || r.missing_skills.length > 0) && (
                  <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 1.5 }} aria-label={t("interviews.my.skills")}>
                    {r.top_skills.map((s) => (
                      <StatusChip key={`s-${s}`} tone="brand" emoji="check" label={s} />
                    ))}
                    {r.missing_skills.map((s) => (
                      <StatusChip key={`m-${s}`} tone="sun" emoji="question" label={t("interviews.my.check_skill", { skill: s })} />
                    ))}
                  </Stack>
                )}

                <Stack direction="row" spacing={1} sx={{ mt: 2 }} flexWrap="wrap" useFlexGap>
                  {join && (
                    <Button variant={tab === "upcoming" ? "contained" : "outlined"} component="a" href={join} target="_blank" rel="noopener noreferrer" startIcon={<Emoji name="link" size={16} />}>
                      {t("interviews.join")}
                    </Button>
                  )}
                  {staff ? (
                    <Button variant="outlined" component={RouterLink} to={`/candidates/${iv.application_id}`}>
                      {t("interviews.action.view")}
                    </Button>
                  ) : r.has_resume && r.candidate_id ? (
                    <Button variant="outlined" startIcon={<Emoji name="page" size={16} />} onClick={() => openBlob(candidatesApi.fetchResumeBlob(r.candidate_id!))}>
                      {t("iv20.resume")}
                    </Button>
                  ) : null}
                  {tab === "upcoming" && !r.interviewer_response && (
                    <>
                      <Button color="warning" onClick={() => setAnswer({ row: r, kind: "reschedule" })}>{t("iv20.propose")}</Button>
                      <Button color="error" onClick={() => setAnswer({ row: r, kind: "declined" })}>{t("iv20.decline")}</Button>
                    </>
                  )}
                  {canWrite && (
                    <Button variant={tab === "feedback" ? "contained" : "text"} onClick={() => setOpenId(isOpen ? null : iv.interview_id)} aria-expanded={isOpen} startIcon={<Emoji name="memo" size={16} />}>
                      {isOpen ? t("interviews.my.hide_scorecard") : t("interviews.action.scorecard")}
                    </Button>
                  )}
                </Stack>

                <Collapse in={isOpen} unmountOnExit timeout={reduced ? 0 : "auto"}>
                  <Box sx={{ mt: 2, pt: 2, borderTop: `1px solid ${f.line}` }}>
                    <ScorecardForm
                      interviewId={iv.interview_id}
                      applicationId={iv.application_id}
                      candidateLabel={name}
                      onCancel={() => setOpenId(null)}
                      onSaved={() => {
                        setOpenId(null);
                        load();
                      }}
                    />
                  </Box>
                </Collapse>
              </Card>
            );
          })}
        </Stack>
      )}
      {answer && <AnswerDialog row={answer.row} kind={answer.kind} onClose={() => setAnswer(null)} onDone={() => { setAnswer(null); load(); }} />}
    </Box>
  );
}

// Part 20.4: "Can't make it" (reason) / "Ask for another time" -> an HR to-do; the interview stays booked until HR changes it.
function AnswerDialog({ row, kind, onClose, onDone }: { row: MyInterviewRow; kind: "declined" | "reschedule"; onClose: () => void; onDone: () => void }) {
  const { t } = useI18n();
  const [reason, setReason] = useState("");
  const [when, setWhen] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      if (kind === "declined") await interviewsExtraApi.decline(row.interview.interview_id, reason);
      else await interviewsExtraApi.proposeTime(row.interview.interview_id, when, reason);
      onDone();
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm" aria-labelledby="iv20-answer-title">
      <DialogTitle id="iv20-answer-title">{t(kind === "declined" ? "iv20.decline_title" : "iv20.propose_title", { name: row.interview.candidate_name ?? "" })}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={1.5}>
          <Typography sx={{ fontSize: 13, color: "text.secondary" }}>{t("iv20.answer_hint")}</Typography>
          {kind === "reschedule" && <TextField label={t("iv20.when")} placeholder={t("iv20.when_ph")} value={when} onChange={(e) => setWhen(e.target.value)} required />}
          <TextField label={t(kind === "declined" ? "iv20.reason" : "iv20.reason_optional")} value={reason} onChange={(e) => setReason(e.target.value)}
            multiline minRows={2} required={kind === "declined"} />
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" color={kind === "declined" ? "error" : "warning"} disabled={busy || (kind === "declined" ? reason.trim().length < 3 : !when.trim())} onClick={send}>
          {t("iv20.send")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
