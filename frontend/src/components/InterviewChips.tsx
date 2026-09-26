import { type InterviewStatus, type SchedulingMethod } from "../api/types";
import { useT } from "../i18n";
import StatusChip from "../ui-kit/StatusChip";
import type { Tone } from "../ui-kit/StatusChip";

// Part 15 B: interview status = colour + emoji + word (never colour alone).
const STATUS_LOOK: Record<InterviewStatus, { tone: Tone; emoji: string }> = {
  upcoming: { tone: "sky", emoji: "calendar" },
  awaiting_feedback: { tone: "sun", emoji: "alarm_clock" },
  selected: { tone: "ok", emoji: "thumbs_up" },
  rejected: { tone: "coral", emoji: "cross" },
};

export function InterviewStatusChip({ status, size }: { status: InterviewStatus; size?: "small" | "medium" }) {
  const t = useT();
  const look = STATUS_LOOK[status] ?? { tone: "muted" as Tone, emoji: "label" };
  return <StatusChip tone={look.tone} emoji={look.emoji} label={t(`interviews.status.${status}`)} size={size} />;
}

// "auto" = the candidate picked the time from the emailed link; "manual" = HR booked it.
export function SchedulingMethodChip({ method }: { method: SchedulingMethod }) {
  const t = useT();
  return method === "auto" ? (
    <StatusChip tone="brand" emoji="link" label={t("interviews.method.auto")} />
  ) : (
    <StatusChip tone="muted" emoji="pencil" label={t("interviews.method.manual")} />
  );
}
