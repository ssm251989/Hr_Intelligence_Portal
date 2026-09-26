import { useEffect, useState, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { offersExtraApi, type OffersUiContext } from "../../api/offersExtra";
import type { JobRoleRead } from "../../api/types";
import { useI18n, useT } from "../../i18n";
import { StatusChip, UserAvatar } from "../../ui-kit";

// Shared bits for the Salary / BGV / Offers pages (Part 15.4).

let contextPromise: Promise<OffersUiContext> | null = null;

/** Company currency + offer expiry days, fetched once per visit. Falls back quietly. */
export function useOffersContext(): OffersUiContext {
  const [ctx, setCtx] = useState<OffersUiContext>({ currency: null, offer_expiry_days: 7 });
  useEffect(() => {
    let alive = true;
    contextPromise ??= offersExtraApi.context().catch(() => {
      contextPromise = null;
      return { currency: null, offer_expiry_days: 7 };
    });
    contextPromise.then((c) => {
      if (alive) setCtx(c);
    });
    return () => {
      alive = false;
    };
  }, []);
  return ctx;
}

function intlLocale(locale: string): string {
  return locale === "en" ? "en-IN" : `${locale}-IN`;
}

/** Money always shown with the company currency symbol when we know it. */
export function useMoney(): (value: number | null | undefined) => string {
  const { locale } = useI18n();
  const { currency } = useOffersContext();
  return (value) => {
    if (value == null || Number.isNaN(Number(value))) return "—";
    const n = Number(value);
    try {
      if (currency) return new Intl.NumberFormat(intlLocale(locale), { style: "currency", currency, maximumFractionDigits: 0 }).format(n);
    } catch {
      /* unknown currency code -- plain number below */
    }
    return n.toLocaleString(intlLocale(locale), { maximumFractionDigits: 0 });
  };
}

/** "26 Sep 2026" / "26 Sep 2026, 10:12" in the user's language. */
export function useWhen(): (iso: string | null | undefined, withTime?: boolean) => string {
  const { locale } = useI18n();
  return (iso, withTime = true) => {
    if (!iso) return "";
    const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(intlLocale(locale), withTime ? { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" } : { day: "numeric", month: "short", year: "numeric" });
  };
}

export function JobPickerCard({
  jobs, value, onChange, hint,
}: {
  jobs: JobRoleRead[];
  value: string;
  onChange: (jobId: string) => void;
  hint: ReactNode;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  return (
    <Card sx={{ p: 2.25, mb: 2.5 }}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ xs: "stretch", md: "center" }}>
        <TextField
          select
          label={t("offers.shared.pick_job")}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          sx={{ minWidth: { md: 320 } }}
          fullWidth
        >
          {jobs.length === 0 && <MenuItem disabled value="">{t("offers.shared.no_jobs")}</MenuItem>}
          {jobs.map((job) => (
            <MenuItem key={job.id} value={job.id}>
              {job.title}
            </MenuItem>
          ))}
        </TextField>
        <Typography sx={{ color: f.muted, fontSize: 14 }}>{hint}</Typography>
      </Stack>
    </Card>
  );
}

/** Person row at the top of every candidate card: initials tile + name + status chip. */
export function PersonHeader({ name, status, subtitle, right }: { name: string; status: string; subtitle?: ReactNode; right?: ReactNode }) {
  const f = useTheme().palette.fresh;
  return (
    <Stack direction="row" spacing={1.5} alignItems="center" justifyContent="space-between" flexWrap="wrap" useFlexGap>
      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minWidth: 0 }}>
        <UserAvatar name={name} size={42} />
        <Box sx={{ minWidth: 0 }}>
          <Typography component="h2" sx={{ fontWeight: 800, fontSize: 17 }}>{name}</Typography>
          {subtitle && <Typography sx={{ color: f.muted, fontSize: 13 }}>{subtitle}</Typography>}
        </Box>
      </Stack>
      <Stack direction="row" spacing={1} alignItems="center">
        {right}
        <StatusChip status={status} size="medium" />
      </Stack>
    </Stack>
  );
}

/** A small labelled figure: "Expected" / "₹ 28,00,000". Numbers never stand alone. */
export function Figure({ label, value, tip }: { label: ReactNode; value: ReactNode; tip?: ReactNode }) {
  const f = useTheme().palette.fresh;
  return (
    <Box sx={{ minWidth: 120 }}>
      <Typography component="div" sx={{ fontSize: 12, color: f.muted, fontWeight: 600, display: "flex", alignItems: "center" }}>
        {label}
        {tip}
      </Typography>
      <Typography component="div" sx={{ fontWeight: 800, fontSize: 16, fontVariantNumeric: "tabular-nums" }}>{value}</Typography>
    </Box>
  );
}

/** Soft inset panel used for sections inside a card (checklist, timeline, forms). */
export function Inset({ title, children, action }: { title?: ReactNode; children: ReactNode; action?: ReactNode }) {
  const f = useTheme().palette.fresh;
  return (
    <Box sx={{ mt: 2, p: 2, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
      {(title || action) && (
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }} spacing={1}>
          {title && <Typography component="h3" sx={{ fontWeight: 700, fontSize: 14 }}>{title}</Typography>}
          {action}
        </Stack>
      )}
      {children}
    </Box>
  );
}
