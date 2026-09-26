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
import { StatusChip } from "../ui-kit";
import { screeningScoreDisplay } from "../utils/screeningScore";
import CandidateAvatar from "./CandidateAvatar";
import { ScoreBadge } from "./screening/ScoreParts";
import SourceIcon from "./SourceIcon";

// RecentCandidatesTable's Shortlisting Dashboard counterpart -- every row here is already
// Shortlisted (hr_selected), so the useful score column is the Screening Score (composite)
// that decision was actually made against, not the raw Match Score.
export default function RecentShortlistedTable({ rows }: { rows: CandidateApplicationRow[] }) {
  const navigate = useNavigate();
  const t = useT();

  if (rows.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        {t("shortlisting.recent.empty")}
      </Typography>
    );
  }

  return (
    <TableContainer>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>{t("screening.col.candidate")}</TableCell>
            <TableCell>{t("screening.col.source")}</TableCell>
            <TableCell>{t("screening.col.job")}</TableCell>
            <TableCell>{t("screening.col.score")}</TableCell>
            <TableCell>{t("screening.col.status")}</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => {
            const { value, tooltip } = screeningScoreDisplay(row);
            const open = () => navigate(`/candidates/${row.application_id}`);
            return (
              <TableRow
                key={row.application_id}
                hover
                onClick={open}
                onKeyDown={(e) => {
                  if (e.key === "Enter") open();
                }}
                tabIndex={0}
                aria-label={t("screening.open_candidate", { name: row.candidate_name || t("screening.unnamed") })}
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
                    <Typography variant="body2" noWrap fontWeight={600}>
                      {row.candidate_name || t("screening.unnamed")}
                    </Typography>
                  </Stack>
                </TableCell>
                <TableCell>
                  <SourceIcon source={row.source} />
                </TableCell>
                <TableCell>{row.job_title}</TableCell>
                <TableCell><ScoreBadge value={value} fallbackHint={tooltip} /></TableCell>
                <TableCell>
                  <StatusChip status="hr_selected" />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
