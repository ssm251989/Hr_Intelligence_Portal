import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { useI18n, useT } from "../../i18n";
import { EmptyState, Emoji, InfoTip, StatusChip, useReducedMotion, type Tone } from "../../ui-kit";

// Part 15.6 -- small pieces shared by the Performance, Compensation and Succession pages.

export function useFresh() {
  return useTheme().palette.fresh;
}

export function intlLocale(locale: string): string {
  return locale === "en" ? "en-IN" : `${locale}-IN`;
}

/** Money in the pay review's own currency; masked values ("••••") pass straight through. */
export function useMoneyFormat(currency: string | null | undefined) {
  const { locale } = useI18n();
  return (value: number | string | null | undefined): string => {
    if (value == null || value === "") return "—";
    if (typeof value === "string" && Number.isNaN(Number(value))) return value;
    const n = Number(value);
    try {
      if (currency) return new Intl.NumberFormat(intlLocale(locale), { style: "currency", currency, maximumFractionDigits: 0 }).format(n);
    } catch {
      /* unknown currency code */
    }
    return n.toLocaleString(intlLocale(locale), { maximumFractionDigits: 0 });
  };
}

export function useDateFormat() {
  const { locale } = useI18n();
  return (iso: string | null | undefined): string => {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(intlLocale(locale), { day: "numeric", month: "short", year: "numeric" });
  };
}

export const isMasked = (v: unknown) => typeof v === "string" && Number.isNaN(Number(v));

/** A slim progress bar that always carries its number in words next to it. */
export function ProgressBar({ value, label, tone = "brand", compact }: { value: number; label?: string; tone?: "brand" | "coral" | "sun" | "ok" | "sky"; compact?: boolean }) {
  const f = useFresh();
  const t = useT();
  const reduced = useReducedMotion();
  const pct = Math.max(0, Math.min(100, Math.round(value)));
  const text = label ?? t("performance.progress_words", { pct });
  return (
    <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: compact ? 120 : 160 }}>
      <Box
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={text}
        sx={{ flex: 1, height: 8, borderRadius: 999, bgcolor: f.line, overflow: "hidden" }}
      >
        <Box sx={{ width: `${pct}%`, height: "100%", bgcolor: f[tone], borderRadius: 999, transition: reduced ? undefined : "width 400ms ease" }} />
      </Box>
      <Typography sx={{ fontSize: 12, fontWeight: 700, color: f.muted, whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>{text}</Typography>
    </Stack>
  );
}

/** Card with an emoji heading, used for every block on these pages. */
export function Panel({ emoji, title, tip, action, children, dataTour }: { emoji: string; title: ReactNode; tip?: string; action?: ReactNode; children: ReactNode; dataTour?: string }) {
  return (
    <Card sx={{ p: { xs: 2, md: 2.5 } }} data-tour={dataTour}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Emoji name={emoji} size={20} />
        <Typography variant="h3" component="h2" sx={{ fontSize: 17, fontWeight: 800, flex: 1 }}>
          {title}
          {tip && <InfoTip text={tip} />}
        </Typography>
        {action}
      </Stack>
      {children}
    </Card>
  );
}

/** Friendly "you can't see this" state (no page chrome guessing). */
export function NoAccess({ what }: { what: string }) {
  const t = useT();
  return (
    <Card>
      <EmptyState
        illustration="access-denied"
        title={t("performance.no_access.title", { what })}
        hint={t("performance.no_access.hint")}
        action={<Button variant="contained" component={RouterLink} to="/">{t("action.go_home")}</Button>}
      />
    </Card>
  );
}

// ---- status chips (colour + emoji + word) ----

const STATUS: Record<string, { tone: Tone; emoji: string }> = {
  active: { tone: "sky", emoji: "hourglass" },
  completed: { tone: "ok", emoji: "check" },
  pending: { tone: "sun", emoji: "hourglass" },
  draft: { tone: "muted", emoji: "pencil" },
  submitted: { tone: "ok", emoji: "check" },
  approved: { tone: "ok", emoji: "check" },
  rejected: { tone: "coral", emoji: "cross" },
  covered: { tone: "ok", emoji: "check" },
  at_risk: { tone: "sun", emoji: "warning" },
  uncovered: { tone: "coral", emoji: "fire" },
  ready_now: { tone: "ok", emoji: "rocket" },
  ready_1_2_years: { tone: "sun", emoji: "seedling" },
  ready_3_plus_years: { tone: "sky", emoji: "compass" },
  checkin_due: { tone: "sun", emoji: "alarm_clock" },
  checkin_ok: { tone: "ok", emoji: "check" },
  low: { tone: "ok", emoji: "check" },
  medium: { tone: "sun", emoji: "warning" },
  high: { tone: "coral", emoji: "fire" },
};

export function PerfChip({ status, label }: { status: string; label?: string }) {
  const t = useT();
  const s = STATUS[status] ?? { tone: "muted" as Tone, emoji: "label" };
  const key = `performance.status.${status}`;
  const text = label ?? (t(key) !== key ? t(key) : status.replace(/_/g, " "));
  return <StatusChip tone={s.tone} emoji={s.emoji} label={text} />;
}

/** Confidence 1-5 as five tappable buttons (radio group). */
export function ConfidencePicker({ value, onChange, disabled }: { value: number | null; onChange: (v: number) => void; disabled?: boolean }) {
  const f = useFresh();
  const t = useT();
  return (
    <Box role="radiogroup" aria-label={t("performance.checkin.confidence")} sx={{ display: "flex", gap: 0.75, flexWrap: "wrap" }}>
      {[1, 2, 3, 4, 5].map((n) => {
        const on = value === n;
        return (
          <Box
            key={n}
            component="button"
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            onClick={() => onChange(n)}
            title={t(`performance.confidence.${n}`)}
            sx={{
              all: "unset", cursor: disabled ? "default" : "pointer", px: 1.25, py: 0.6, borderRadius: 999, fontWeight: 700, fontSize: 13,
              border: `1px solid ${on ? f.brand : f.line}`, bgcolor: on ? f.brandSoft : f.surface, color: on ? f.brand : f.ink,
              "&:focus-visible": { outline: `2px solid ${f.brand}`, outlineOffset: 2 },
            }}
          >
            {n} · {t(`performance.confidence.${n}`)}
          </Box>
        );
      })}
    </Box>
  );
}
