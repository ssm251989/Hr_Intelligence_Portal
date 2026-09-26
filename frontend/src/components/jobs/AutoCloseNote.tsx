import type { ReactNode } from "react";
import Stack from "@mui/material/Stack";

import type { JobPipelineRow } from "../../api/jobsExtra";
import { useT } from "../../i18n";
import { InfoTip, StatusChip } from "../../ui-kit";

// J5: say, in words, when a job will close by itself (all openings filled OR its closing
// date passes) -- or why it already did.
export default function AutoCloseNote({ row, withTip = false }: { row: JobPipelineRow | undefined; withTip?: boolean }) {
  const t = useT();
  if (!row) return null;
  const chips: ReactNode[] = [];
  if (row.status === "closed" && row.auto_closed) {
    chips.push(
      <StatusChip key="closed" tone="muted" emoji={row.auto_closed.reason === "positions_filled" ? "party" : "alarm_clock"}
        label={t(row.auto_closed.reason === "positions_filled" ? "jobs.autoclose.filled" : "jobs.autoclose.deadline")} />,
    );
  }
  if (row.status === "published") {
    if (row.days_to_close != null) {
      const soon = row.days_to_close <= 3;
      chips.push(
        <StatusChip key="date" tone={soon ? "sun" : "muted"} emoji="alarm_clock"
          label={row.days_to_close <= 0 ? t("jobs.autoclose.closes_today") : t("jobs.autoclose.closes_in", { count: row.days_to_close })} />,
      );
    }
    if (row.hired > 0) {
      chips.push(<StatusChip key="left" tone={row.positions_left <= 1 ? "sun" : "muted"} emoji="people" label={t("jobs.autoclose.left", { count: row.positions_left })} />);
    }
  }
  if (chips.length === 0) return null;
  return (
    <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap" useFlexGap>
      {chips}
      {withTip && <InfoTip text={t("jobs.autoclose.tip")} />}
    </Stack>
  );
}
