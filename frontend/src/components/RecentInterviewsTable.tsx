import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { Link as RouterLink, useNavigate } from "react-router-dom";

import type { InterviewListRow } from "../api/types";
import { useI18n } from "../i18n";
import EmptyState from "../ui-kit/EmptyState";
import UserAvatar from "../ui-kit/UserAvatar";
import { InterviewStatusChip, SchedulingMethodChip } from "./InterviewChips";
import { localeTag } from "./interviews/weekDates";

// The Interview Dashboard's Recent Interviews table -- same "click a row -> candidate
// detail" pattern as RecentCandidatesTable/RecentShortlistedTable (rows are also reachable
// by keyboard: Tab to the row, Enter opens it).
export default function RecentInterviewsTable({ rows }: { rows: InterviewListRow[] }) {
  const navigate = useNavigate();
  const { t, locale } = useI18n();
  const fmt = new Intl.DateTimeFormat(localeTag(locale), { dateStyle: "medium", timeStyle: "short" });

  if (rows.length === 0) {
    return (
      <EmptyState
        compact
        illustration="calendar"
        title={t("interviews.empty.none")}
        action={<Button variant="contained" component={RouterLink} to="/interviews/list">{t("interviews.empty.go_schedule")}</Button>}
      />
    );
  }

  return (
    <TableContainer>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>{t("interviews.col.candidate")}</TableCell>
            <TableCell>{t("interviews.col.job")}</TableCell>
            <TableCell>{t("interviews.col.interviewer")}</TableCell>
            <TableCell>{t("interviews.col.when")}</TableCell>
            <TableCell>{t("interviews.col.method")}</TableCell>
            <TableCell>{t("interviews.col.status")}</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => {
            const name = row.candidate_name || t("interviews.unnamed");
            const open = () => navigate(`/candidates/${row.application_id}`);
            return (
              <TableRow
                key={row.interview_id}
                hover
                tabIndex={0}
                aria-label={t("interviews.open_candidate", { name })}
                onClick={open}
                onKeyDown={(e) => {
                  if (e.key === "Enter") open();
                }}
                sx={{ cursor: "pointer" }}
              >
                <TableCell>
                  <Stack direction="row" spacing={1.25} alignItems="center">
                    <UserAvatar name={name} size={30} />
                    <Typography variant="body2" fontWeight={600} noWrap>
                      {name}
                    </Typography>
                  </Stack>
                </TableCell>
                <TableCell>{row.job_title}</TableCell>
                <TableCell>{row.interviewer_name || t("interviews.unassigned")}</TableCell>
                <TableCell sx={{ whiteSpace: "nowrap" }}>{row.scheduled_at ? fmt.format(new Date(row.scheduled_at)) : t("interviews.no_time")}</TableCell>
                <TableCell>
                  <SchedulingMethodChip method={row.scheduling_method} />
                </TableCell>
                <TableCell>
                  <InterviewStatusChip status={row.status} />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
