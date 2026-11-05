import Box from "@mui/material/Box";
import { useTheme } from "@mui/material/styles";

import { useT } from "../i18n";
import Emoji from "./Emoji";

// Part 15 B: a status is ALWAYS colour + emoji + word, never colour alone.
export type Tone = "ok" | "sun" | "coral" | "sky" | "brand" | "muted";

export interface StatusStyle {
  tone: Tone;
  emoji: string;
  label: string;
}

// The five core states from the spec, then every status string the app shows.
export const STATUS_STYLES: Record<string, StatusStyle> = {
  done: { tone: "ok", emoji: "check", label: "Done" },
  due_soon: { tone: "sun", emoji: "alarm_clock", label: "Due soon" },
  overdue: { tone: "coral", emoji: "fire", label: "Overdue" },
  new: { tone: "sky", emoji: "new", label: "New" },
  on_hold: { tone: "muted", emoji: "pause", label: "On hold" },
  // application pipeline
  received: { tone: "sky", emoji: "inbox", label: "Received" },
  screened: { tone: "sky", emoji: "magnifier", label: "Screened" },
  hr_selected: { tone: "ok", emoji: "star", label: "Shortlisted" },
  hr_rejected: { tone: "coral", emoji: "cross", label: "Not selected" },
  interview_scheduled: { tone: "sky", emoji: "calendar", label: "Interview booked" },
  interview_selected: { tone: "ok", emoji: "thumbs_up", label: "Passed interview" },
  interview_rejected: { tone: "coral", emoji: "cross", label: "Did not pass" },
  salary_ok: { tone: "ok", emoji: "money", label: "Salary in band" },
  salary_above_band: { tone: "sun", emoji: "warning", label: "Above salary band" },
  salary_approved: { tone: "ok", emoji: "check", label: "Salary approved" },
  salary_rejected: { tone: "coral", emoji: "cross", label: "Salary declined" },
  bgv_requested: { tone: "sky", emoji: "shield", label: "Checks requested" },
  bgv_pending: { tone: "sun", emoji: "hourglass", label: "Checks in progress" },
  bgv_cleared: { tone: "ok", emoji: "shield", label: "Checks cleared" },
  bgv_rejected: { tone: "coral", emoji: "cross", label: "Checks failed" },
  offer_sent: { tone: "sky", emoji: "envelope", label: "Offer sent" },
  onboarding_started: { tone: "brand", emoji: "waving_hand", label: "Onboarding" },
  onboarding_completed: { tone: "ok", emoji: "party", label: "Joined" },
  // fix 2026-10-05: how an offer / a new joiner ended
  offer_withdrawn: { tone: "coral", emoji: "cross", label: "Offer withdrawn" },
  offer_declined: { tone: "muted", emoji: "speech", label: "Offer declined" },
  no_show: { tone: "coral", emoji: "pause", label: "Did not join" },
  left_after_joining: { tone: "muted", emoji: "door", label: "Left after joining" },
  // jobs
  draft: { tone: "muted", emoji: "pencil", label: "Draft" },
  ready_for_publishing: { tone: "sun", emoji: "hourglass", label: "Ready to publish" },
  published: { tone: "ok", emoji: "globe", label: "Open" },
  closed: { tone: "muted", emoji: "lock", label: "Closed" },
  // documents / checks
  valid: { tone: "ok", emoji: "check", label: "Verified" },
  invalid: { tone: "coral", emoji: "cross", label: "Not valid" },
  needs_review: { tone: "sun", emoji: "eyes", label: "Needs a look" },
  pending: { tone: "sun", emoji: "hourglass", label: "Waiting" },
  // generic workflow words
  approved: { tone: "ok", emoji: "check", label: "Approved" },
  rejected: { tone: "coral", emoji: "cross", label: "Declined" },
  open: { tone: "sky", emoji: "new", label: "Open" },
  in_progress: { tone: "sky", emoji: "hourglass", label: "In progress" },
  resolved: { tone: "ok", emoji: "check", label: "Resolved" },
  cancelled: { tone: "muted", emoji: "cross", label: "Cancelled" },
  signed: { tone: "ok", emoji: "writing_hand", label: "Signed" },
  viewed: { tone: "sky", emoji: "eyes", label: "Viewed" },
  sent: { tone: "sky", emoji: "envelope", label: "Sent" },
  failed: { tone: "coral", emoji: "warning", label: "Failed" },
  active: { tone: "ok", emoji: "check", label: "Active" },
  inactive: { tone: "muted", emoji: "pause", label: "Inactive" },
};

export function humanise(status: string): string {
  const words = status.replace(/[_-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : words;
}

export function statusStyle(status: string): StatusStyle {
  return STATUS_STYLES[status] ?? { tone: "muted", emoji: "label", label: humanise(status) };
}

export function useToneColours(tone: Tone): { bg: string; fg: string } {
  const t = useTheme().palette.fresh;
  const map: Record<Tone, { bg: string; fg: string }> = {
    ok: { bg: t.okSoft, fg: t.ok }, sun: { bg: t.sunSoft, fg: t.sunInk }, coral: { bg: t.coralSoft, fg: t.coral },
    sky: { bg: t.skySoft, fg: t.sky }, brand: { bg: t.brandSoft, fg: t.brand }, muted: { bg: t.surface2, fg: t.muted },
  };
  return map[tone];
}

/** <StatusChip status="overdue" /> or a custom one: <StatusChip tone="sun" emoji="alarm_clock" label="2h left" />. */
export default function StatusChip({ status, tone, emoji, label, size = "small" }: { status?: string; tone?: Tone; emoji?: string; label?: string; size?: "small" | "medium" }) {
  const base = status ? statusStyle(status) : { tone: "muted" as Tone, emoji: "label", label: "" };
  const finalTone = tone ?? base.tone;
  const { bg, fg } = useToneColours(finalTone);
  const t = useTheme().palette.fresh;
  const tt = useT();
  const key = status ? `status.${status}` : "";
  const translated = key ? tt(key) : "";
  const text = label ?? (translated && translated !== key ? translated : base.label);
  return (
    <Box
      component="span"
      sx={{
        display: "inline-flex", alignItems: "center", gap: 0.5, borderRadius: 999, px: size === "small" ? 1.1 : 1.4, py: size === "small" ? 0.35 : 0.6,
        fontSize: size === "small" ? 12 : 13, fontWeight: 700, whiteSpace: "nowrap", bgcolor: bg, color: fg, lineHeight: 1.3,
        border: finalTone === "muted" ? `1px solid ${t.line}` : "1px solid transparent",
      }}
    >
      <Emoji name={emoji ?? base.emoji} size={size === "small" ? 14 : 16} />
      {text}
    </Box>
  );
}
