import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { useNavigate } from "react-router-dom";

import type { InterviewListRow } from "../api/types";
import { InterviewStatusChip, SchedulingMethodChip } from "./InterviewChips";

// The Interview Dashboard's Recent Interviews table -- same "click a row -> candidate
// detail" pattern as RecentCandidatesTable/RecentShortlistedTable.
export default function RecentInterviewsTable({ rows }: { rows: InterviewListRow[] }) {
  const navigate = useNavigate();

  if (rows.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        No interviews scheduled yet.
      </Typography>
    );
  }

  return (
    <TableContainer>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Candidate</TableCell>
            <TableCell>Job</TableCell>
            <TableCell>Interviewer</TableCell>
            <TableCell>Scheduled Time</TableCell>
            <TableCell>Method</TableCell>
            <TableCell>Status</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow
              key={row.interview_id}
              hover
              onClick={() => navigate(`/candidates/${row.application_id}`)}
              sx={{ cursor: "pointer" }}
            >
              <TableCell>
                <Typography variant="body2" noWrap>
                  {row.candidate_name || "Unnamed candidate"}
                </Typography>
              </TableCell>
              <TableCell>{row.job_title}</TableCell>
              <TableCell>{row.interviewer_name || "Unassigned"}</TableCell>
              <TableCell>{row.scheduled_at ? new Date(row.scheduled_at).toLocaleString() : "—"}</TableCell>
              <TableCell>
                <SchedulingMethodChip method={row.scheduling_method} />
              </TableCell>
              <TableCell>
                <InterviewStatusChip status={row.status} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
