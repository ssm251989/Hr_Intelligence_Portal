import type { JobStage } from "../../api/jobsExtra";
import type { Tone } from "../../ui-kit";

// The plain hiring steps the Jobs table counts candidates in (backend STAGE_OF_STATUS in
// app/experience/ui_jobs_router.py maps every application status onto one of these).
export const STAGE_STYLE: Record<JobStage, { emoji: string; tone: Tone }> = {
  new: { emoji: "inbox", tone: "sky" },
  screening: { emoji: "magnifier", tone: "sky" },
  shortlisted: { emoji: "star", tone: "brand" },
  interview: { emoji: "calendar", tone: "sun" },
  offer: { emoji: "envelope", tone: "coral" },
  hired: { emoji: "party", tone: "ok" },
  not_selected: { emoji: "cross", tone: "muted" },
  paused: { emoji: "pause", tone: "muted" },
};
