import Chip from "@mui/material/Chip";
import type { ChipProps } from "@mui/material/Chip";

type JobTypeColor = "success" | "info" | "warning";

// backend/app/models/job_role.py JOB_TYPES
const JOB_TYPE_COLOR_MAP: Record<string, JobTypeColor> = {
  "Full-time": "success",
  "Part-time": "info",
  Contract: "warning",
};

export function jobTypeColor(jobType: string): JobTypeColor {
  return JOB_TYPE_COLOR_MAP[jobType] ?? "info";
}

export default function JobTypeChip({ jobType, size = "small" }: { jobType: string; size?: ChipProps["size"] }) {
  return <Chip label={jobType} color={jobTypeColor(jobType)} size={size} />;
}
