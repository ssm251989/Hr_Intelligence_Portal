import type { AuditLogRead } from "../../api/types";
import { useT, type TFunction } from "../../i18n";
import { humanise, Timeline, type TimelineItem } from "../../ui-kit";
import { activityEmoji } from "./stages";

// Part 15.4 C6: the candidate's history (emails, stage changes, notes, interviews, AI
// scores) from the existing audit-trail endpoint, newest first, in plain words.

export function timeAgo(t: TFunction, isoTimestamp: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(isoTimestamp).getTime()) / 1000);
  if (seconds < 60) return t("candidates.time.just_now");
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t("candidates.time.minutes", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("candidates.time.hours", { count: hours });
  return t("candidates.time.days", { count: Math.floor(hours / 24) });
}

export function activityLabel(t: TFunction, action: string | null | undefined): string {
  const a = action ?? "";
  const key = `candidates.activity.${a}`;
  const text = t(key);
  return text === key ? humanise(a) || t("candidates.activity.generic") : text;
}

function detailLine(t: TFunction, event: AuditLogRead): string | null {
  const d = (event.details ?? {}) as Record<string, unknown>;
  if (event.action === "ai_screening_scored" && typeof d.composite_score === "number") {
    return t("candidates.activity.score_detail", { score: Math.round(d.composite_score) });
  }
  if (typeof d.subject === "string" && d.subject) return `“${d.subject}”`;
  if (typeof d.feedback === "string" && d.feedback) return `“${d.feedback}”`;
  if (typeof d.reason === "string" && d.reason) return d.reason;
  return null;
}

export default function ActivityTimeline({ events, filter }: { events: AuditLogRead[]; filter?: (e: AuditLogRead) => boolean }) {
  const t = useT();
  const items: TimelineItem[] = [...events]
    .filter((e) => (filter ? filter(e) : true))
    .reverse()
    .map((event) => {
      const who = event.actor && event.actor !== "system" ? ` · ${event.actor}` : "";
      const extra = detailLine(t, event);
      return {
        id: String(event.id),
        emoji: activityEmoji(event.action),
        title: activityLabel(t, event.action),
        meta: `${timeAgo(t, event.created_at)} · ${new Date(event.created_at).toLocaleString()}${who}${extra ? ` · ${extra}` : ""}`,
      };
    });
  return <Timeline items={items} empty={t("candidates.activity.empty")} />;
}
