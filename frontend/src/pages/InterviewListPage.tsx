import { useEffect, useMemo, useState } from "react";
import AddOutlinedIcon from "@mui/icons-material/AddOutlined";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import CalendarViewWeekOutlinedIcon from "@mui/icons-material/CalendarViewWeekOutlined";
import EditNoteOutlinedIcon from "@mui/icons-material/EditNoteOutlined";
import LinkOutlinedIcon from "@mui/icons-material/LinkOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import TableRowsOutlinedIcon from "@mui/icons-material/TableRowsOutlined";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import FormControl from "@mui/material/FormControl";
import IconButton from "@mui/material/IconButton";
import InputLabel from "@mui/material/InputLabel";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Pagination from "@mui/material/Pagination";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useNavigate, useSearchParams } from "react-router-dom";

import { jobsApi, schedulingApi, usersApi } from "../api/client";
import { INTERVIEW_STATUSES, type InterviewListRow, type InterviewStatus, type JobRoleRead, type SchedulingMethod, type UserRead } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";
import InterviewFeedbackDialog from "../components/InterviewFeedbackDialog";
import InterviewFiltersPanel, { EMPTY_INTERVIEW_FILTERS, type InterviewFilters } from "../components/InterviewFiltersPanel";
import { InterviewStatusChip, SchedulingMethodChip } from "../components/InterviewChips";
import InterviewPrepQuestionsDialog from "../components/InterviewPrepQuestionsDialog";
import ListToolbar, { type ListColumn, type ListViewState } from "../components/ListToolbar";
import ScheduleInterviewDialog from "../components/ScheduleInterviewDialog";
import { AI_INTERVIEW_FEATURE } from "../components/interviews/AiQuestionsSection";
import InterviewQuickView from "../components/interviews/InterviewQuickView";
import InterviewWeekCalendar from "../components/interviews/InterviewWeekCalendar";
import { addDays, isoDate, localeTag, startOfWeek } from "../components/interviews/weekDates";
import { useI18n } from "../i18n";
import EmptyState from "../ui-kit/EmptyState";
import FriendlyError from "../ui-kit/FriendlyError";
import PageHeader from "../ui-kit/PageHeader";
import UserAvatar from "../ui-kit/UserAvatar";

const ROWS_PER_PAGE_OPTIONS = [10, 25, 50, 100];
const DEFAULT_PAGE_SIZE = 25;
const VIEW_STORAGE_KEY = "hrms.interviews.view";
type ViewMode = "table" | "week";

function readStoredView(): ViewMode {
  try {
    return localStorage.getItem(VIEW_STORAGE_KEY) === "week" ? "week" : "table";
  } catch {
    return "table";
  }
}

function InterviewActionsMenu({
  row,
  canWrite,
  aiAllowed,
  onView,
  onRecordFeedback,
  onPrepQuestions,
}: {
  row: InterviewListRow;
  canWrite: boolean;
  aiAllowed: boolean;
  onView: (applicationId: string) => void;
  onRecordFeedback: (row: InterviewListRow) => void;
  onPrepQuestions: (row: InterviewListRow) => void;
}) {
  const { t } = useI18n();
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const join = row.meeting_link || row.calendar_link;
  const name = row.candidate_name || t("interviews.unnamed");

  return (
    <>
      <IconButton size="small" aria-label={t("interviews.action.menu", { name })} aria-haspopup="menu" onClick={(e) => setAnchorEl(e.currentTarget)}>
        <MoreVertIcon fontSize="small" />
      </IconButton>
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
        <MenuItem
          onClick={() => {
            setAnchorEl(null);
            onView(row.application_id);
          }}
        >
          <VisibilityOutlinedIcon fontSize="small" sx={{ mr: 1 }} />
          {t("interviews.action.view")}
        </MenuItem>
        {join && (
          <MenuItem component="a" href={join} target="_blank" rel="noopener noreferrer" onClick={() => setAnchorEl(null)}>
            <LinkOutlinedIcon fontSize="small" sx={{ mr: 1 }} />
            {t("interviews.join")}
          </MenuItem>
        )}
        {canWrite && (
          <MenuItem
            onClick={() => {
              setAnchorEl(null);
              onRecordFeedback(row);
            }}
          >
            <EditNoteOutlinedIcon fontSize="small" sx={{ mr: 1 }} />
            {t("interviews.action.scorecard")}
          </MenuItem>
        )}
        {canWrite && aiAllowed && (
          <MenuItem
            onClick={() => {
              setAnchorEl(null);
              onPrepQuestions(row);
            }}
          >
            <AutoAwesomeOutlinedIcon fontSize="small" sx={{ mr: 1 }} />
            {t("interviews.action.questions")}
          </MenuItem>
        )}
      </Menu>
    </>
  );
}

// The Interview List -- table (default, 25 rows) or week calendar (spec I1), both with the
// same filters. Scoped to the `interviews` table across every job (backend
// app/scheduling/router.py list_all_interviews). Reschedule/Cancel aren't row actions:
// neither exists as a backend endpoint today.
export default function InterviewListPage() {
  const navigate = useNavigate();
  const theme = useTheme();
  const f = theme.palette.fresh;
  const { t, locale } = useI18n();
  const { can } = useAuth();
  const { aiFeature } = useMeBootstrap();
  const canWrite = can(ROLE_MATRIX.interviewsWrite);
  const aiAllowed = aiFeature(AI_INTERVIEW_FEATURE);
  const [searchParams] = useSearchParams();

  const columns: ListColumn[] = useMemo(
    () => [
      { key: "candidate_name", label: t("interviews.col.candidate") },
      { key: "job_title", label: t("interviews.col.job") },
      { key: "interviewer_name", label: t("interviews.col.interviewer") },
      { key: "scheduled_at", label: t("interviews.col.when") },
      { key: "scheduling_method", label: t("interviews.col.method") },
      { key: "status", label: t("interviews.col.status") },
    ],
    [t],
  );

  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [interviewers, setInterviewers] = useState<UserRead[]>([]);
  const [rows, setRows] = useState<InterviewListRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const initialStatus = searchParams.get("status");
  const [filters, setFilters] = useState<InterviewFilters>({
    ...EMPTY_INTERVIEW_FILTERS,
    status: initialStatus && (INTERVIEW_STATUSES as string[]).includes(initialStatus) ? initialStatus : "",
  });
  const [visibleColumns, setVisibleColumns] = useState<string[]>(columns.map((c) => c.key));
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  // Forces loadPage to re-run on Refresh even when every filter/page value already
  // happens to be at its default (in which case none of the other deps below would change).
  const [refreshKey, setRefreshKey] = useState(0);
  const anyFilterActive = Object.values(filters).some(Boolean);

  const [view, setView] = useState<ViewMode>(() => (searchParams.get("view") === "week" ? "week" : readStoredView()));
  const [weekStart, setWeekStart] = useState<Date>(() => startOfWeek(new Date()));

  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [feedbackRow, setFeedbackRow] = useState<InterviewListRow | null>(null);
  const [prepQuestionsRow, setPrepQuestionsRow] = useState<InterviewListRow | null>(null);
  const [quickRow, setQuickRow] = useState<InterviewListRow | null>(null);

  useEffect(() => {
    jobsApi.list().then(setJobs).catch(() => setJobs([]));
    usersApi.list("interviewer").then(setInterviewers).catch(() => setInterviewers([]));
  }, []);

  useEffect(() => {
    setPage(1);
  }, [filters]);

  const changeView = (next: ViewMode | null) => {
    if (!next) return;
    setView(next);
    try {
      localStorage.setItem(VIEW_STORAGE_KEY, next);
    } catch {
      /* per-visit only */
    }
  };

  const loadPage = () => {
    setLoading(true);
    setError(null);
    const common = {
      jobRoleId: filters.jobRoleId || undefined,
      interviewerId: filters.interviewerId || undefined,
      status: (filters.status || undefined) as InterviewStatus | undefined,
      schedulingMethod: (filters.schedulingMethod || undefined) as SchedulingMethod | undefined,
    };
    // The week view asks for one day either side so a time-zone edge never drops an
    // interview; the calendar itself only draws the seven days it shows.
    const request =
      view === "week"
        ? schedulingApi.listAll({ ...common, page: 1, pageSize: 200, scheduledAfter: isoDate(addDays(weekStart, -1)), scheduledBefore: isoDate(addDays(weekStart, 7)) })
        : schedulingApi.listAll({ ...common, page, pageSize, scheduledAfter: filters.scheduledAfter || undefined, scheduledBefore: filters.scheduledBefore || undefined });
    request
      .then((result) => {
        setRows(result.items);
        setTotal(result.total);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, filters, refreshKey, view, weekStart]);

  const handleRefresh = () => {
    setFilters(EMPTY_INTERVIEW_FILTERS);
    setPage(1);
    setPageSize(DEFAULT_PAGE_SIZE);
    setRefreshKey((k) => k + 1);
  };

  const viewState: ListViewState = { columns: visibleColumns, filters: { ...filters } };
  const onViewStateChange = (next: ListViewState) => {
    if (Array.isArray(next.columns)) setVisibleColumns(next.columns);
    if (next.filters && typeof next.filters === "object") setFilters({ ...EMPTY_INTERVIEW_FILTERS, ...(next.filters as Partial<InterviewFilters>) });
  };

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const pageStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = Math.min(page * pageSize, total);

  const handlePageSizeChange = (event: SelectChangeEvent<number>) => {
    setPageSize(Number(event.target.value));
    setPage(1);
  };

  const rowLabel = (row: InterviewListRow) => row.candidate_name || t("interviews.unnamed");
  const dateFmt = new Intl.DateTimeFormat(localeTag(locale), { dateStyle: "medium", timeStyle: "short" });
  const shown = columns.filter((c) => visibleColumns.includes(c.key));
  const exportRows = rows.map((r) => ({
    ...r,
    candidate_name: rowLabel(r),
    interviewer_name: r.interviewer_name || t("interviews.unassigned"),
    scheduled_at: r.scheduled_at ? dateFmt.format(new Date(r.scheduled_at)) : "",
    scheduling_method: t(`interviews.method.${r.scheduling_method}`),
    status: t(`interviews.status.${r.status}`),
  }));

  const cell = (row: InterviewListRow, key: string) => {
    switch (key) {
      case "candidate_name":
        return (
          <Stack direction="row" spacing={1.25} alignItems="center" sx={{ minWidth: 0 }}>
            <UserAvatar name={rowLabel(row)} size={34} />
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2" fontWeight={600} noWrap>
                {rowLabel(row)}
              </Typography>
              {row.candidate_email && (
                <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>
                  {row.candidate_email}
                </Typography>
              )}
            </Box>
          </Stack>
        );
      case "job_title":
        return row.job_title;
      case "interviewer_name":
        return row.interviewer_name || t("interviews.unassigned");
      case "scheduled_at":
        return <Box sx={{ whiteSpace: "nowrap" }}>{row.scheduled_at ? dateFmt.format(new Date(row.scheduled_at)) : t("interviews.no_time")}</Box>;
      case "scheduling_method":
        return <SchedulingMethodChip method={row.scheduling_method} />;
      case "status":
        return <InterviewStatusChip status={row.status} />;
      default:
        return null;
    }
  };

  const emptyAction = anyFilterActive ? (
    <Button variant="outlined" onClick={() => setFilters(EMPTY_INTERVIEW_FILTERS)}>
      {t("interviews.filter.reset")}
    </Button>
  ) : canWrite ? (
    <Button variant="contained" startIcon={<AddOutlinedIcon />} onClick={() => setScheduleOpen(true)}>
      {t("interviews.list.schedule")}
    </Button>
  ) : undefined;

  return (
    <Box>
      <PageHeader
        emoji="calendar"
        title={t("interviews.list.title")}
        purpose={t("interviews.list.purpose")}
        tourKey="interviews"
        primary={
          canWrite ? (
            <Button variant="contained" startIcon={<AddOutlinedIcon />} onClick={() => setScheduleOpen(true)}>
              {t("interviews.list.schedule")}
            </Button>
          ) : undefined
        }
      />

      <Card sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: "column", lg: "row" }} spacing={1.5} alignItems={{ xs: "stretch", lg: "center" }} justifyContent="space-between">
          <InterviewFiltersPanel jobs={jobs} interviewers={interviewers} filters={filters} onChange={setFilters} hideDates={view === "week"} />
          <ToggleButtonGroup exclusive size="small" value={view} onChange={(_e, v: ViewMode | null) => changeView(v)} aria-label={t("interviews.list.view_label")}
            sx={{ alignSelf: { xs: "flex-start", lg: "center" }, "& .MuiToggleButton-root": { textTransform: "none", fontWeight: 700, px: 1.5, gap: 0.75 } }}>
            <ToggleButton value="table" aria-label={t("interviews.list.view_table")}>
              <TableRowsOutlinedIcon fontSize="small" />
              {t("interviews.list.view_table")}
            </ToggleButton>
            <ToggleButton value="week" aria-label={t("interviews.list.view_week")}>
              <CalendarViewWeekOutlinedIcon fontSize="small" />
              {t("interviews.list.view_week")}
            </ToggleButton>
          </ToggleButtonGroup>
        </Stack>
      </Card>

      <ListToolbar
        listKey="interviews.list"
        columns={columns}
        state={viewState}
        onStateChange={onViewStateChange}
        rows={exportRows as unknown as Record<string, unknown>[]}
        loading={loading}
        onRefresh={handleRefresh}
      />

      {error ? (
        <Box sx={{ mb: 2 }}>
          <FriendlyError error={error} onRetry={loadPage} />
        </Box>
      ) : view === "week" ? (
        <InterviewWeekCalendar weekStart={weekStart} onWeekChange={(d) => setWeekStart(startOfWeek(d))} rows={rows} loading={loading} onOpen={setQuickRow} />
      ) : loading ? (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  {shown.map((c) => (
                    <TableCell key={c.key}>{c.label}</TableCell>
                  ))}
                  <TableCell align="right">{t("interviews.col.actions")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {Array.from({ length: 5 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: shown.length + 1 }).map((__, j) => (
                      <TableCell key={j}>
                        <Skeleton variant="text" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            illustration="calendar"
            title={total === 0 && !anyFilterActive ? t("interviews.empty.none") : t("interviews.empty.filtered")}
            hint={total === 0 && !anyFilterActive ? t("interviews.empty.none_hint") : undefined}
            action={emptyAction}
          />
        </Card>
      ) : (
        <>
          <Card>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    {shown.map((c) => (
                      <TableCell key={c.key}>{c.label}</TableCell>
                    ))}
                    <TableCell align="right">{t("interviews.col.actions")}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.interview_id} hover>
                      {shown.map((c) => (
                        <TableCell key={c.key}>{cell(row, c.key)}</TableCell>
                      ))}
                      <TableCell align="right">
                        <InterviewActionsMenu
                          row={row}
                          canWrite={canWrite}
                          aiAllowed={aiAllowed}
                          onView={(applicationId) => navigate(`/candidates/${applicationId}`)}
                          onRecordFeedback={setFeedbackRow}
                          onPrepQuestions={setPrepQuestionsRow}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Card>

          <Stack direction="row" justifyContent="space-between" alignItems="center" mt={2} flexWrap="wrap" gap={1}>
            <Typography variant="body2" sx={{ color: f.muted }}>
              {t("interviews.list.showing", { start: pageStart, end: pageEnd, count: total })}
            </Typography>
            <Stack direction="row" spacing={2} alignItems="center">
              <FormControl size="small" sx={{ minWidth: 130 }}>
                <InputLabel id="interviews-rows-per-page-label">{t("interviews.list.rows_per_page")}</InputLabel>
                <Select labelId="interviews-rows-per-page-label" label={t("interviews.list.rows_per_page")} value={pageSize} onChange={handlePageSizeChange}>
                  {ROWS_PER_PAGE_OPTIONS.map((size) => (
                    <MenuItem key={size} value={size}>
                      {size}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Pagination count={pageCount} page={page} onChange={(_e, value) => setPage(value)} size="small" color="primary" />
            </Stack>
          </Stack>
        </>
      )}

      <InterviewQuickView
        row={quickRow}
        canWrite={canWrite}
        aiAllowed={aiAllowed}
        onClose={() => setQuickRow(null)}
        onViewCandidate={(row) => navigate(`/candidates/${row.application_id}`)}
        onScorecard={(row) => {
          setQuickRow(null);
          setFeedbackRow(row);
        }}
        onQuestions={(row) => {
          setQuickRow(null);
          setPrepQuestionsRow(row);
        }}
      />

      <ScheduleInterviewDialog
        open={scheduleOpen}
        onClose={() => setScheduleOpen(false)}
        onScheduled={() => {
          setScheduleOpen(false);
          loadPage();
        }}
      />

      <InterviewFeedbackDialog
        interviewId={feedbackRow?.interview_id ?? null}
        applicationId={feedbackRow?.application_id ?? null}
        candidateLabel={feedbackRow ? rowLabel(feedbackRow) : ""}
        onClose={() => setFeedbackRow(null)}
        onSaved={() => {
          setFeedbackRow(null);
          loadPage();
        }}
      />

      <InterviewPrepQuestionsDialog
        applicationId={prepQuestionsRow?.application_id ?? null}
        candidateLabel={prepQuestionsRow ? rowLabel(prepQuestionsRow) : ""}
        onClose={() => setPrepQuestionsRow(null)}
      />
    </Box>
  );
}
