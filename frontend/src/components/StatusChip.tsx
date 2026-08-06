import Chip from "@mui/material/Chip";
import type { ChipProps } from "@mui/material/Chip";

type StatusColor = "default" | "success" | "warning" | "error" | "info";

// Every status string used as a Chip label anywhere in the app -- application pipeline
// statuses, job posting statuses, and BGV document validation statuses. None of these
// values collide across domains, so one flat map covers all of them.
const STATUS_COLOR_MAP: Record<string, StatusColor> = {
  // application pipeline (backend/app/models/application.py APPLICATION_STATUSES)
  received: "default",
  screened: "default",
  hr_selected: "success",
  hr_rejected: "error",
  interview_scheduled: "default",
  interview_selected: "success",
  interview_rejected: "error",
  salary_ok: "success",
  salary_above_band: "warning",
  salary_approved: "success",
  salary_rejected: "error",
  bgv_requested: "default",
  bgv_pending: "warning",
  bgv_cleared: "success",
  bgv_rejected: "error",
  offer_sent: "default",
  onboarding_started: "default",
  onboarding_completed: "success",
  // job postings (backend/app/models/job_role.py)
  draft: "default",
  ready_for_publishing: "warning",
  published: "success",
  closed: "error",
  // BGV document validation (backend/app/schemas/bgv.py)
  valid: "success",
  invalid: "error",
  needs_review: "warning",
  pending: "default",
};

export function statusColor(status: string): StatusColor {
  return STATUS_COLOR_MAP[status] ?? "default";
}

export function statusLabel(status: string): string {
  return status
    .split("_")
    .map((word) => (word ? word[0].toUpperCase() + word.slice(1) : word))
    .join(" ");
}

export default function StatusChip({ status, size = "small" }: { status: string; size?: ChipProps["size"] }) {
  return <Chip label={statusLabel(status)} color={statusColor(status)} size={size} />;
}
