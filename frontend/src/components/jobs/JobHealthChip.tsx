import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import WarningAmberOutlinedIcon from "@mui/icons-material/WarningAmberOutlined";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import type { JobHealthIssueKind, JobHealthRow, JobHealthTip } from "../../api/automationApi";
import { useT, type TFunction } from "../../i18n";

const TIP_KEY: Record<JobHealthTip, string> = {
  share_again: "autom.health.tip.share", widen_location: "autom.health.tip.location", relax_skills: "autom.health.tip.relax",
  decide_waiting: "autom.health.tip.decide", check_scoring: "autom.health.tip.threshold",
};

/** Part 18.7: one issue in plain words ("No new applicants for 33 days", "2 candidates waiting ..."). */
export function issueText(t: TFunction, issue: { kind: JobHealthIssueKind; days: number; count: number }): string {
  if (issue.kind === "no_applicants") return t("jobhealth.issue.no_applicants", { days: issue.days });
  if (issue.kind === "slow_stage") return t(issue.count === 1 ? "jobhealth.issue.slow_one" : "jobhealth.issue.slow", { count: issue.count, days: issue.days });
  return t("jobhealth.issue.low_scores", { count: issue.count });
}

export function tipText(t: TFunction, tip: JobHealthTip): string {
  return t(TIP_KEY[tip]);
}

/** Green / amber / red chip for the Jobs table; hover shows the reasons and what to try. */
export default function JobHealthChip({ row }: { row?: JobHealthRow }) {
  const t = useT();
  if (!row) return <>—</>;
  const meta = {
    green: { color: "success" as const, icon: <CheckCircleOutlineIcon />, label: t("jobhealth.level.green") },
    amber: { color: "warning" as const, icon: <WarningAmberOutlinedIcon />, label: t("jobhealth.level.amber") },
    red: { color: "error" as const, icon: <ErrorOutlineIcon />, label: t("jobhealth.level.red") },
  }[row.level];
  const chip = <Chip size="small" color={meta.color} icon={meta.icon} label={meta.label} />;
  if (row.level === "green") return chip;
  return (
    <Tooltip
      title={
        <Box sx={{ py: 0.5 }}>
          {row.issues.map((i) => <Typography key={i.kind} variant="body2" sx={{ fontWeight: 700 }}>• {issueText(t, i)}</Typography>)}
          {row.tips.length > 0 && (
            <>
              <Typography variant="caption" sx={{ display: "block", mt: 0.75, color: "inherit", opacity: 0.8 }}>{t("autom.health.try")}</Typography>
              {row.tips.map((tip) => <Typography key={tip} variant="caption" sx={{ display: "block", color: "inherit" }}>– {tipText(t, tip)}</Typography>)}
            </>
          )}
        </Box>
      }
    >
      <span>{chip}</span>
    </Tooltip>
  );
}
