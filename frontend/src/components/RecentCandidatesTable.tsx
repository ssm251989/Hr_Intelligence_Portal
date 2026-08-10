import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import IconButton from "@mui/material/IconButton";
import Avatar from "@mui/material/Avatar";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useNavigate } from "react-router-dom";

import type { CandidateApplicationRow } from "../api/types";
import { initials } from "../utils/avatar";
import { resumeHref } from "../utils/resume";
import SourceChip from "./SourceChip";
import StatusChip from "./StatusChip";

export default function RecentCandidatesTable({ rows }: { rows: CandidateApplicationRow[] }) {
  const navigate = useNavigate();

  if (rows.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        No candidates yet.
      </Typography>
    );
  }

  return (
    <TableContainer>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Candidate</TableCell>
            <TableCell>Job Applied</TableCell>
            <TableCell>Stage</TableCell>
            <TableCell>Source</TableCell>
            <TableCell>Applied On</TableCell>
            <TableCell>Match Score</TableCell>
            <TableCell>Experience</TableCell>
            <TableCell align="right">Resume</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => {
            const href = resumeHref(row.candidate_id, row.resume_path);
            return (
              <TableRow
                key={row.application_id}
                hover
                onClick={() => navigate(`/candidates/${row.application_id}`)}
                sx={{ cursor: "pointer" }}
              >
                <TableCell>
                  <Stack direction="row" spacing={1.25} alignItems="center">
                    <Avatar sx={{ width: 28, height: 28, fontSize: 12, bgcolor: "primary.main" }}>
                      {initials(row.candidate_name || row.candidate_email || "?")}
                    </Avatar>
                    <Typography variant="body2" noWrap>
                      {row.candidate_name || "Unnamed candidate"}
                    </Typography>
                  </Stack>
                </TableCell>
                <TableCell>{row.job_title}</TableCell>
                <TableCell>
                  <StatusChip status={row.status} />
                </TableCell>
                <TableCell>
                  <SourceChip source={row.source} />
                </TableCell>
                <TableCell>{new Date(row.applied_on).toLocaleDateString()}</TableCell>
                <TableCell>{row.match_score != null ? `${Math.round(row.match_score)}%` : "—"}</TableCell>
                <TableCell>{row.experience_years != null ? `${row.experience_years}y` : "—"}</TableCell>
                <TableCell align="right" onClick={(e) => e.stopPropagation()}>
                  {href ? (
                    <Tooltip title="View resume">
                      <IconButton size="small" component="a" href={href} target="_blank" rel="noreferrer">
                        <DescriptionOutlinedIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  ) : (
                    "—"
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
