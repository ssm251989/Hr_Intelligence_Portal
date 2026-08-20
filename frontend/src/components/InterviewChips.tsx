import Chip from "@mui/material/Chip";
import type { ChipProps } from "@mui/material/Chip";

import { INTERVIEW_STATUS_LABELS, SCHEDULING_METHOD_LABELS, type InterviewStatus, type SchedulingMethod } from "../api/types";

const STATUS_COLOR: Record<InterviewStatus, ChipProps["color"]> = {
  upcoming: "info",
  awaiting_feedback: "warning",
  selected: "success",
  rejected: "error",
};

export function InterviewStatusChip({ status }: { status: InterviewStatus }) {
  return <Chip label={INTERVIEW_STATUS_LABELS[status]} size="small" color={STATUS_COLOR[status]} variant="outlined" />;
}

// Manual gets no color emphasis (the original, default flow); Auto is called out since
// it's the new Part 3 candidate-confirmed path recruiters will want to spot at a glance.
export function SchedulingMethodChip({ method }: { method: SchedulingMethod }) {
  return (
    <Chip
      label={SCHEDULING_METHOD_LABELS[method]}
      size="small"
      color={method === "auto" ? "primary" : "default"}
      variant={method === "auto" ? "filled" : "outlined"}
    />
  );
}
