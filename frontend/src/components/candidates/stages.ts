import { useTheme } from "@mui/material/styles";

import { isTerminalApplicationStatus } from "../../api/types";
import { FRESH, type FreshTokens } from "../../theme/tokens";

// Part 15.4 Candidates restyle: one place that turns the raw pipeline status
// (backend app/models/application.py APPLICATION_STATUSES) into the friendly stage groups
// shown on the Kanban board and the profile's stage stepper.

/** Theme tokens with a safe fallback (unit tests render without the app ThemeProvider). */
export function useFresh(): FreshTokens {
  const theme = useTheme();
  return (theme.palette as { fresh?: FreshTokens }).fresh ?? FRESH[theme.palette.mode === "dark" ? "dark" : "light"];
}

export type BoardColumnKey =
  | "new" | "screened" | "shortlisted" | "interview" | "checks" | "offer" | "joined" | "on_hold" | "not_moving";

export interface BoardColumn {
  key: BoardColumnKey;
  emoji: string;
  statuses: string[];
}

export const BOARD_COLUMNS: BoardColumn[] = [
  { key: "new", emoji: "inbox", statuses: ["received"] },
  { key: "screened", emoji: "magnifier", statuses: ["screened"] },
  { key: "shortlisted", emoji: "star", statuses: ["hr_selected"] },
  { key: "interview", emoji: "calendar", statuses: ["interview_scheduled", "interview_selected"] },
  { key: "checks", emoji: "shield", statuses: ["salary_ok", "salary_above_band", "salary_approved", "bgv_requested", "bgv_pending", "bgv_cleared"] },
  { key: "offer", emoji: "envelope", statuses: ["offer_sent", "onboarding_started"] },
  { key: "joined", emoji: "party", statuses: ["onboarding_completed"] },
  { key: "on_hold", emoji: "pause", statuses: ["on_hold"] },
  { key: "not_moving", emoji: "cross", statuses: ["hr_rejected", "interview_rejected", "salary_rejected", "bgv_rejected"] },
];

export function columnOf(status: string): BoardColumnKey {
  return BOARD_COLUMNS.find((c) => c.statuses.includes(status))?.key ?? "new";
}

// ---- drag / "move to" rules --------------------------------------------------------
// Only moves that an existing endpoint already performs are allowed; everything else snaps
// back with a sentence saying where that step really happens.
export type MovePlan =
  | { kind: "hold" }
  | { kind: "resume" }
  | { kind: "shortlist" }
  | { kind: "not_shortlist" }
  | { kind: "blocked"; reasonKey: string };

export function planMove(status: string, to: BoardColumnKey): MovePlan | null {
  const from = columnOf(status);
  if (from === to) return null;
  if (to === "on_hold") {
    return isTerminalApplicationStatus(status) ? { kind: "blocked", reasonKey: "candidates.move.blocked_final" } : { kind: "hold" };
  }
  if (status === "on_hold") return { kind: "resume" };
  if (status === "screened" && to === "shortlisted") return { kind: "shortlist" };
  if (status === "screened" && to === "not_moving") return { kind: "not_shortlist" };
  if (isTerminalApplicationStatus(status)) return { kind: "blocked", reasonKey: "candidates.move.blocked_final" };
  const reasons: Record<BoardColumnKey, string> = {
    new: "candidates.move.blocked_new",
    screened: "candidates.move.blocked_screened",
    shortlisted: "candidates.move.blocked_shortlisted",
    interview: "candidates.move.blocked_interview",
    checks: "candidates.move.blocked_checks",
    offer: "candidates.move.blocked_offer",
    joined: "candidates.move.blocked_joined",
    on_hold: "candidates.move.blocked_final",
    not_moving: "candidates.move.blocked_not_moving",
  };
  return { kind: "blocked", reasonKey: reasons[to] };
}

// ---- profile stage stepper ----------------------------------------------------------
export const STEPPER_STAGES = ["applied", "screened", "shortlisted", "interview", "checks", "offer", "joined"] as const;

export function stepperIndex(status: string, previousStatus?: string | null): number {
  const s = status === "on_hold" && previousStatus ? previousStatus : status;
  switch (columnOf(s)) {
    case "new": return 0;
    case "screened": return 1;
    case "shortlisted": return 2;
    case "interview": return 3;
    case "checks": return 4;
    case "offer": return 5;
    case "joined": return 6;
    default:
      if (s === "hr_rejected") return 2;
      if (s === "interview_rejected") return 3;
      if (s === "salary_rejected" || s === "bgv_rejected") return 4;
      return 0;
  }
}

// ---- activity timeline ----------------------------------------------------------------
/** Emoji per audit action (emails, stage changes, notes, interviews, AI scores). */
export function activityEmoji(action: string | null | undefined): string {
  const a = action ?? "";
  if (a.startsWith("ai_")) return "robot";
  if (a.includes("message") || a.includes("email") || a.includes("mail")) return "envelope";
  if (a.includes("interview")) return "calendar";
  if (a.includes("hold")) return "pause";
  if (a.includes("shortlist")) return "star";
  if (a.includes("salary")) return "money";
  if (a.includes("bgv")) return "shield";
  if (a.includes("offer")) return "writing_hand";
  if (a.includes("onboarding")) return "waving_hand";
  if (a.includes("note") || a.includes("feedback")) return "memo";
  if (a.includes("upload") || a.includes("created") || a.includes("applied")) return "inbox";
  if (a.includes("updated") || a.includes("status")) return "pencil";
  return "label";
}
