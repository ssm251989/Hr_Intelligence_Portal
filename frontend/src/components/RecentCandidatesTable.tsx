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
import { useT } from "../i18n";
import { matchScoreDisplay } from "../utils/screeningScore";
import CandidateAvatar from "./CandidateAvatar";
import SourceIcon from "./SourceIcon";

export default function RecentCandidatesTable({ rows }: { rows: CandidateApplicationRow[] }) {
  const t = useT();
  const navigate = useNavigate();

  if (rows.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        {t("candidates.dash.recent_empty")}
      </Typography>
    );
  }

  return (
    <TableContainer>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>{t("candidates.col.candidate")}</TableCell>
            <TableCell>{t("candidates.col.source")}</TableCell>
            <TableCell>{t("candidates.col.job")}</TableCell>
            <TableCell>{t("candidates.col.applied")}</TableCell>
            <TableCell>{t("candidates.col.match")}</TableCell>
            <TableCell>{t("candidates.col.experience")}</TableCell>
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
                    {row.candidate_name || t("candidates.unnamed")}
                  </Typography>
                </Stack>
              </TableCell>
              <TableCell>
                <SourceIcon source={row.source} />
              </TableCell>
              <TableCell>{row.job_title}</TableCell>
              <TableCell>{new Date(row.applied_on).toLocaleDateString()}</TableCell>
              <TableCell>
                {(() => {
                  const { value } = matchScoreDisplay(row, t);
                  return value != null ? Math.round(value) : "—";
                })()}
              </TableCell>
              <TableCell>{row.experience_years != null ? t("candidates.years", { count: row.experience_years }) : "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
