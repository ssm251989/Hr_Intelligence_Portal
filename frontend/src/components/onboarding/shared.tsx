import { useI18n } from "../../i18n";
import { StatusChip } from "../../ui-kit";

// Part 15.6 onboarding helpers shared by the HR dashboard and the pre-joiner portal.

export function intlLocale(locale: string): string {
  return locale === "en" ? "en-IN" : `${locale}-IN`;
}

/** "Mon, 5 Oct" style dates in the reader's language. Dates are plain YYYY-MM-DD (no timezone shift). */
export function useDateText() {
  const { locale } = useI18n();
  const loc = intlLocale(locale);
  const parse = (iso: string) => {
    const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
    return new Date(y, (m || 1) - 1, d || 1);
  };
  return {
    day: (iso: string) => parse(iso).toLocaleDateString(loc, { weekday: "short", day: "numeric", month: "short" }),
    long: (iso: string) => parse(iso).toLocaleDateString(loc, { weekday: "long", day: "numeric", month: "long" }),
    when: (iso: string) => new Date(iso).toLocaleString(loc, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }),
  };
}

/** Joining-date group by calendar week (Monday start) relative to `today`. */
export type JoinGroup = "passed" | "this_week" | "next_week" | "later";

export function joinGroup(daysToJoin: number, today: Date = new Date()): JoinGroup {
  if (daysToJoin < 0) return "passed";
  const weekday = (today.getDay() + 6) % 7; // Monday = 0
  const daysLeftThisWeek = 6 - weekday;
  if (daysToJoin <= daysLeftThisWeek) return "this_week";
  if (daysToJoin <= daysLeftThisWeek + 7) return "next_week";
  return "later";
}

/** Case status as colour + emoji + word. */
export function JoinerStatusChip({ status, t }: { status: string; t: (k: string) => string }) {
  switch (status) {
    case "invited":
      return <StatusChip tone="sky" emoji="envelope" label={t("onboarding.status.invited")} />;
    case "in_progress":
      return <StatusChip tone="sun" emoji="hourglass" label={t("onboarding.status.in_progress")} />;
    case "ready":
      return <StatusChip tone="ok" emoji="check" label={t("onboarding.status.ready")} />;
    case "joined":
      return <StatusChip tone="ok" emoji="party" label={t("onboarding.status.joined")} />;
    case "no_show":
      return <StatusChip tone="muted" emoji="pause" label={t("onboarding.status.no_show")} />;
    case "revoked":
      return <StatusChip tone="muted" emoji="cross" label={t("onboarding.status.revoked")} />;
    default:
      return <StatusChip status={status} />;
  }
}

/** Who a plan task belongs to, in plain words. */
export function ownerText(role: string, t: (k: string) => string): string {
  const key = `onboarding.owner.${role}`;
  const text = t(key);
  return text === key ? role : text;
}
