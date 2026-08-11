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
import CandidateAvatar from "./CandidateAvatar";
import SourceIcon from "./SourceIcon";

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
            <TableCell>Source</TableCell>
            <TableCell>Applied For</TableCell>
            <TableCell>Applied On</TableCell>
            <TableCell>Match Score</TableCell>
            <TableCell>Experience</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
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
              <TableCell>{new Date(row.applied_on).toLocaleDateString()}</TableCell>
              <TableCell>{row.match_score != null ? `${Math.round(row.match_score)}%` : "—"}</TableCell>
              <TableCell>{row.experience_years != null ? `${row.experience_years}y` : "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
