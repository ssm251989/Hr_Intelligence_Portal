import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { useI18n, useT } from "../../i18n";
import { Emoji, EmptyState, StatusChip, type Tone } from "../../ui-kit";

// Part 15.6 People screens -- small pieces shared by the Employees list, profile, directory
// and org chart.

const EMPLOYEE_STATUS: Record<string, { tone: Tone; emoji: string }> = {
  pre_hire: { tone: "sky", emoji: "waving_hand" },
  active: { tone: "ok", emoji: "check" },
  on_notice: { tone: "sun", emoji: "hourglass" },
  inactive: { tone: "muted", emoji: "pause" },
  terminated: { tone: "muted", emoji: "door" },
  rehire_eligible: { tone: "brand", emoji: "handshake" },
};

export const EMPLOYEE_STATUSES = Object.keys(EMPLOYEE_STATUS);

/** Colour + emoji + word for an employee's status ("Working here", "Serving notice"...). */
export function EmployeeStatusChip({ status, size }: { status: string; size?: "small" | "medium" }) {
  const t = useT();
  const s = EMPLOYEE_STATUS[status] ?? { tone: "muted" as Tone, emoji: "label" };
  return <StatusChip tone={s.tone} emoji={s.emoji} label={t(`people.status.${status}`)} size={size} />;
}

export function useFormatDate() {
  const { locale } = useI18n();
  return (iso?: string | null, withTime = false): string => {
    if (!iso) return "—";
    const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
    if (Number.isNaN(d.getTime())) return "—";
    const tag = locale === "en" ? "en-IN" : `${locale}-IN`;
    return withTime
      ? d.toLocaleString(tag, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })
      : d.toLocaleDateString(tag, { day: "numeric", month: "short", year: "numeric" });
  };
}

/** Friendly "no access" state (kept on the page instead of a bare 403). */
export function NoAccess({ emoji = "people", title }: { emoji?: string; title?: string }) {
  const t = useT();
  return (
    <Card sx={{ p: 2 }}>
      <EmptyState
        illustration="access-denied"
        title={title ?? t("people.no_access.title")}
        hint={t("people.no_access.hint")}
        action={<Button variant="contained" component={RouterLink} to="/" startIcon={<Emoji name={emoji} size={16} />}>{t("action.go_home")}</Button>}
      />
    </Card>
  );
}

/** A card with an emoji + heading, used for every section on the profile. */
export function SectionCard({ emoji, title, action, children }: { emoji: string; title: ReactNode; action?: ReactNode; children: ReactNode }) {
  return (
    <Card sx={{ height: "100%" }}>
      <Box sx={{ p: { xs: 2, sm: 2.5 } }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1} sx={{ mb: 1.5 }}>
          <Typography variant="h6" component="h2" sx={{ display: "flex", alignItems: "center", gap: 1, fontWeight: 800 }}>
            <Emoji name={emoji} size={20} />
            {title}
          </Typography>
          {action}
        </Stack>
        {children}
      </Box>
    </Card>
  );
}

/** Label / value pair for read-only details. */
export function Field({ label, value, tip, badge }: { label: ReactNode; value: ReactNode; tip?: ReactNode; badge?: ReactNode }) {
  const f = useTheme().palette.fresh;
  const empty = value === null || value === undefined || value === "";
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography component="div" sx={{ fontSize: 12, fontWeight: 700, color: f.muted, textTransform: "uppercase", letterSpacing: 0.4, display: "flex", alignItems: "center" }}>
        {label}
        {tip}
      </Typography>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.25, flexWrap: "wrap", rowGap: 0.5 }}>
        <Typography component="div" sx={{ fontWeight: 600, color: empty ? f.muted : f.ink, overflowWrap: "anywhere" }}>{empty ? "—" : value}</Typography>
        {badge}
      </Stack>
    </Box>
  );
}

/** "Waiting for approval" badge shown next to a field that has a change in flight. */
export function PendingBadge({ label }: { label?: string }) {
  const t = useT();
  return <StatusChip tone="sun" emoji="hourglass" label={label ?? t("people.pending.badge")} />;
}

/** Turns the loose JSON lists on the employee record (addresses, contacts, education...) into readable lines. */
export function describeItem(item: unknown): string {
  if (item === null || item === undefined) return "";
  if (typeof item === "string" || typeof item === "number") return String(item);
  if (typeof item === "object") {
    return Object.values(item as Record<string, unknown>)
      .filter((v) => v !== null && v !== undefined && v !== "" && typeof v !== "object")
      .map(String)
      .join(" · ");
  }
  return "";
}

export function listOf(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.map(describeItem).filter(Boolean);
}
