// This app only operates in India, so times entered by users are always India Standard
// Time (IST, UTC+5:30, no DST). IST_OFFSET_MINUTES is a fixed constant rather than a
// real IANA timezone lookup because IST never changes.
const IST_OFFSET_MINUTES = 5 * 60 + 30;

/**
 * Converts a `<input type="datetime-local">` value (e.g. "2026-08-10T12:20", no timezone
 * of its own) into a UTC ISO string, treating the wall-clock value as IST explicitly.
 *
 * Do NOT use `new Date(value).toISOString()` for this: a timezone-less string is parsed
 * by the JS Date constructor as local time in whatever timezone the browser's own clock
 * happens to be set to, which silently produces the wrong instant if that isn't IST.
 */
export function istLocalInputToUtcIso(localValue: string): string {
  const asIfUtc = new Date(`${localValue}:00.000Z`);
  return new Date(asIfUtc.getTime() - IST_OFFSET_MINUTES * 60 * 1000).toISOString();
}

/** The current IST wall-clock time as a `<input type="datetime-local">` value -- the earliest bookable time (I1, Part 27). */
export function istLocalInputNow(now: Date = new Date()): string {
  return new Date(now.getTime() + IST_OFFSET_MINUTES * 60 * 1000).toISOString().slice(0, 16);
}

/** I2 (Part 27): a meeting link must be an http(s) web address. */
export function isWebLink(value: string): boolean {
  try {
    const u = new URL(value.trim());
    return (u.protocol === "https:" || u.protocol === "http:") && !!u.host && !/\s/.test(value.trim());
  } catch {
    return false;
  }
}

/** Part 27 (cross-cutting): ONE date format - the company locale (en-IN by default), day + short month, and the
 * year whenever it is not this year (or always, when `year: "always"`). */
export function formatDate(iso: string | Date | null | undefined, opts: { year?: "auto" | "always"; locale?: string } = {}): string {
  if (!iso) return "";
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return "";
  const withYear = opts.year === "always" || d.getFullYear() !== new Date().getFullYear();
  return d.toLocaleDateString(opts.locale ?? "en-IN", { day: "numeric", month: "short", ...(withYear ? { year: "numeric" } : {}) });
}

/** formatDate + the time ("1 Jan 2025, 10:00 am"). */
export function formatDateTime(iso: string | Date | null | undefined, opts: { year?: "auto" | "always"; locale?: string } = {}): string {
  if (!iso) return "";
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return "";
  return `${formatDate(d, opts)}, ${d.toLocaleTimeString(opts.locale ?? "en-IN", { hour: "numeric", minute: "2-digit" })}`;
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const MONTH_ABBREVIATIONS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** Formats a "YYYY-MM" month key (as returned by the dashboard stats API) as e.g. "May 2026". */
export function formatMonthKey(monthKey: string): string {
  const [year, month] = monthKey.split("-").map(Number);
  return `${MONTH_NAMES[month - 1]} ${year}`;
}

/** Formats a "YYYY-MM" month key as its 3-letter abbreviation, e.g. "May" (for chart axes). */
export function formatMonthAbbrev(monthKey: string): string {
  const month = Number(monthKey.split("-")[1]);
  return MONTH_ABBREVIATIONS[month - 1];
}

/**
 * The past N *completed* calendar months (most recent first) as "YYYY-MM" keys --
 * matches the range the backend's compare_month query param accepts (it excludes the
 * current, still-in-progress month).
 */
export function pastMonthKeys(count = 12): string[] {
  const now = new Date();
  const keys: string[] = [];
  for (let i = 1; i <= count; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    keys.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  }
  return keys;
}
