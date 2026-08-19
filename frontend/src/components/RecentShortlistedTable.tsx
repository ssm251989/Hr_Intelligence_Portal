import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { useNavigate } from "react-router-dom";

import type { CandidateApplicationRow } from "../api/types";
import { screeningScoreDisplay } from "../utils/screeningScore";
import CandidateAvatar from "./CandidateAvatar";
import SourceIcon from "./SourceIcon";

// RecentCandidatesTable's Shortlisting Dashboard counterpart -- every row here is already
// Shortlisted (hr_selected), so the useful score column is the Screening Score (composite)
// that decision was actually made against, not the raw Match Score, plus a status chip
// since (unlike the Candidates Dashboard's recent list) every one of these rows shares the
// same real meaning: "currently shortlisted for this job."
export default function RecentShortlistedTable({ rows }: { rows: CandidateApplicationRow[] }) {
  const navigate = useNavigate();

  if (rows.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        No candidates shortlisted yet.
      </Typography>
    );
  }

  return (
    <TableContainer>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Candidate</TableCell>
            <TableCell>Source</TableCell>
            <TableCell>Job</TableCell>
            <TableCell>Screening Score</TableCell>
            <TableCell>Status</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => {
            const { value } = screeningScoreDisplay(row);
            return (
              <TableRow
                key={row.application_id}
                hover
                onClick={() => navigate(`/candidates/${row.application_id}`)}
                sx={{ cursor: "pointer" }}
              >
                <TableCell>
                  <Stack direction="row" spacing={1.25} alignItems="center">
                    <CandidateAvatar
                      candidateId={row.candidate_id}
                      photoPath={row.photo_path}
                      name={row.candidate_name}
                      email={row.candidate_email}
                      sx={{ width: 28, height: 28, fontSize: 12 }}
                    />
                    <Typography variant="body2" noWrap>
                      {row.candidate_name || "Unnamed candidate"}
                    </Typography>
                  </Stack>
                </TableCell>
                <TableCell>
                  <SourceIcon source={row.source} />
                </TableCell>
                <TableCell>{row.job_title}</TableCell>
                <TableCell>{value != null ? `${Math.round(value)}%` : "—"}</TableCell>
                <TableCell>
                  <Chip label="Shortlisted" size="small" color="success" variant="outlined" />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
