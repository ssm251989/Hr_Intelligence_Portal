import { useId } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis } from "recharts";
import type { SvgIconComponent } from "@mui/icons-material";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import TrendingFlatIcon from "@mui/icons-material/TrendingFlat";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import type { MonthlyPoint, StatTrend } from "../api/types";
import { formatMonthKey } from "../utils/datetime";
import { CARD_SHADOW_HOVER } from "../theme/tokens";

interface Props {
  label: string;
  value: string | number;
  icon?: SvgIconComponent;
  color?: string;
  trend?: StatTrend;
  // Whether an increase is the desirable direction for this metric (default true --
  // false for e.g. Avg Time to Hire, where a smaller number is better).
  higherIsBetter?: boolean;
  formatSparklineValue?: (value: number) => string;
  // The one "headline" card (Total Jobs) gets a subtle gradient wash in its own accent
  // color -- everything else stays flat so the hero card actually reads as the hero.
  hero?: boolean;
  // "default": icon beside a label/value/trend column, with a sparkline underneath --
  // the Jobs dashboard's style. "compact": icon badge on its own row above a stacked
  // label/value/trend, no sparkline -- denser, for rows of many equal-weight cards
  // (Candidates dashboard) where a sparkline per card would take too much vertical space.
  variant?: "default" | "compact";
}

type SparklineDatum = { month: string; value: number | null };

function SparklineTooltip({
  active,
  payload,
  formatValue,
}: {
  active?: boolean;
  payload?: { payload: SparklineDatum }[];
  formatValue?: (value: number) => string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload;
  if (point.value == null) return null;
  return (
    <Box sx={{ bgcolor: "background.paper", border: 1, borderColor: "divider", borderRadius: 1, px: 1, py: 0.5 }}>
      <Typography variant="caption" fontWeight="bold" display="block">
        {formatValue ? formatValue(point.value) : point.value}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {formatMonthKey(point.month)}
      </Typography>
    </Box>
  );
}

function Sparkline({
  series,
  color,
  formatValue,
}: {
  series: MonthlyPoint[];
  color: string;
  formatValue?: (value: number) => string;
}) {
  // Unique per card instance -- every card renders its own <defs>, and SVG gradient ids
  // must not collide across the 6 that share the page, or one card's fill leaks into another.
  const gradientId = `stat-sparkline-gradient-${useId().replace(/:/g, "")}`;
  const data: SparklineDatum[] = series.map((point) => ({ month: point.month, value: point.value }));
  const lastIndex = data.length - 1;

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.28} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="month" hide />
        <YAxis hide domain={["auto", "auto"]} />
        <RechartsTooltip
          isAnimationActive={false}
          content={<SparklineTooltip formatValue={formatValue} />}
        />
        <Area
          // "natural" still passes exactly through every one of the 12 real monthly
          // values (unlike "basis", which only approximates them) but its cubic spline
          // isn't constrained against overshoot the way "monotone" is, so it curves more
          // freely between points -- the smoother, more organic look asked for here.
          type="natural"
          dataKey="value"
          stroke={color}
          strokeWidth={2}
          fill={`url(#${gradientId})`}
          isAnimationActive={false}
          connectNulls
          dot={(dotProps: { cx?: number; cy?: number; index?: number; value?: number | null }) => {
            const { cx, cy, index, value } = dotProps;
            if (value == null || cx == null || cy == null) {
              return <g key={`dot-${index}`} />;
            }
            // Every real month gets a small marker now; the current (latest) month's is
            // deliberately bigger so the "now" end of the trend still stands out.
            const isCurrent = index === lastIndex;
            return (
              <circle
                key={`dot-${index}`}
                cx={cx}
                cy={cy}
                r={isCurrent ? 4 : 2.5}
                fill={color}
                stroke="var(--mui-palette-background-paper, #fff)"
                strokeWidth={isCurrent ? 2 : 1}
              />
            );
          }}
          activeDot={{ r: 4, fill: color }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function ApproximateBadge() {
  return (
    <Tooltip
      title="Approximate for past months: this status isn't tracked historically, so it's based on jobs that already existed by that month, using their current status."
      arrow
    >
      <InfoOutlinedIcon sx={{ fontSize: 12, color: "text.disabled" }} />
    </Tooltip>
  );
}

function TrendIndicator({
  trend,
  higherIsBetter = true,
  isApproximate,
  dense = false,
}: {
  trend: StatTrend;
  higherIsBetter?: boolean;
  isApproximate?: boolean;
  // Single line ("↑ 4.2% vs July 2026") for the compact card layout, instead of the
  // default two-line form (arrow+pct on its own line, "vs <month>" below it) used
  // alongside the sparkline in the non-compact card.
  dense?: boolean;
}) {
  const { pct_change: pctChange, compare_month: compareMonth, compare_value: compareValue } = trend;
  const compareLabel = formatMonthKey(compareMonth);

  // compare_value of exactly 0 with an undefined pct_change means the compare month was
  // truly zero while the current value isn't (see app/reports/stats.py::pct_change -- a
  // percentage from zero is mathematically undefined, so the backend sends null rather
  // than a real number here). Rather than leaving the card blank, show a placeholder
  // "+100%" -- not a computed percentage, just a "grew from nothing" indicator using the
  // same arrow+percentage visual language as every other card.
  const isZeroBaselineGrowth = pctChange == null && compareValue === 0;
  const displayPct = isZeroBaselineGrowth ? 100 : pctChange;

  if (displayPct == null) {
    // Truly nothing to compare on either side (e.g. Avg Time to Hire with no hires in
    // either month) -- compare_value itself is null here, not 0.
    return (
      <Stack direction="row" spacing={0.4} alignItems="center">
        <Typography variant="caption" color="text.secondary">
          — vs {compareLabel}
        </Typography>
        {isApproximate && <ApproximateBadge />}
      </Stack>
    );
  }

  const direction = displayPct > 0 ? "up" : displayPct < 0 ? "down" : "flat";
  const isGood = direction === "flat" ? null : direction === (higherIsBetter ? "up" : "down");
  const tone = isGood == null ? "text.secondary" : isGood ? "success.main" : "error.main";
  // "flat" only happens when pct_change is a real, computed 0 (both months genuinely
  // equal -- see the displayPct == null branch above for "nothing to compare at all").
  // Still worth a neutral marker, not just bare "0%", so every card reads consistently.
  const ArrowIcon = direction === "down" ? ArrowDownwardIcon : direction === "up" ? ArrowUpwardIcon : TrendingFlatIcon;
  const pctLabel = isZeroBaselineGrowth ? "+100%" : `${Math.abs(displayPct)}%`;

  if (dense) {
    return (
      <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap">
        <ArrowIcon sx={{ fontSize: 14, color: tone }} />
        <Typography variant="caption" fontWeight="bold" sx={{ color: tone }}>
          {pctLabel}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          vs {compareLabel}
        </Typography>
        {isApproximate && <ApproximateBadge />}
      </Stack>
    );
  }

  return (
    <Box>
      <Stack direction="row" spacing={0.5} alignItems="center">
        <ArrowIcon sx={{ fontSize: 14, color: tone }} />
        <Typography variant="caption" fontWeight="bold" sx={{ color: tone }}>
          {pctLabel}
        </Typography>
      </Stack>
      <Stack direction="row" spacing={0.4} alignItems="center">
        <Typography variant="caption" color="text.secondary">
          vs {compareLabel}
        </Typography>
        {isApproximate && <ApproximateBadge />}
      </Stack>
    </Box>
  );
}

export function StatCardSkeleton({ variant = "default" }: { variant?: "default" | "compact" }) {
  if (variant === "compact") {
    return (
      <Card variant="outlined" sx={{ flex: "1 1 200px" }}>
        <CardContent>
          <Stack direction="row" spacing={1.25} alignItems="center">
            <Skeleton variant="rounded" width={40} height={40} sx={{ borderRadius: "10px", flexShrink: 0 }} />
            <Skeleton variant="text" width="60%" />
          </Stack>
          <Skeleton variant="text" width="45%" height={36} />
          <Skeleton variant="text" width="50%" />
        </CardContent>
      </Card>
    );
  }
  return (
    <Card variant="outlined" sx={{ flex: "1 1 220px" }}>
      <CardContent>
        <Stack direction="row" spacing={1.5} alignItems="flex-start">
          <Skeleton variant="circular" width={40} height={40} />
          <Box sx={{ minWidth: 0, flexGrow: 1 }}>
            <Skeleton variant="text" width="60%" />
            <Skeleton variant="text" width="45%" height={36} />
            <Skeleton variant="text" width="70%" />
          </Box>
        </Stack>
        <Skeleton variant="rounded" height={36} sx={{ mt: 1.5 }} />
      </CardContent>
    </Card>
  );
}

export default function StatCard({
  label,
  value,
  icon: Icon,
  color,
  trend,
  higherIsBetter,
  formatSparklineValue,
  hero = false,
  variant = "default",
}: Props) {
  const badgeColor = color || "primary.main";

  if (variant === "compact") {
    return (
      <Card
        variant="outlined"
        sx={(theme) => ({
          height: "100%",
          transition: "transform 220ms ease, box-shadow 220ms ease",
          "&:hover": {
            transform: "translateY(-3px)",
            boxShadow: CARD_SHADOW_HOVER[theme.palette.mode === "dark" ? "dark" : "light"],
          },
        })}
      >
        <CardContent>
          {/* No margin below this row, by design -- matches the Jobs dashboard's default
              variant below (label Typography directly followed by the value Typography,
              no mb/mt between them at all). Same underlying rule in both variants: nothing
              explicit between the label and the number, just their own zero-margin
              Typography default. */}
          <Stack direction="row" spacing={1.25} alignItems="center">
            {Icon && (
              <Box
                sx={{
                  width: 40,
                  height: 40,
                  borderRadius: "10px",
                  bgcolor: color ? `${color}1A` : "action.selected",
                  color: badgeColor,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <Icon fontSize="small" />
              </Box>
            )}
            <Typography variant="body2" sx={{ fontWeight: 600, color: "text.primary" }}>
              {label}
            </Typography>
          </Stack>
          {/* Indented to align under the label text rather than the icon badge above it --
              the icon is 40px wide plus the Stack's 1.25 (10px) gap to the label. */}
          <Typography variant="h4" sx={{ lineHeight: 1.2, fontSize: "1.75rem", fontWeight: 700, pl: Icon ? "50px" : 0 }}>
            {value}
          </Typography>
          {trend && (
            <Box mt={0.375} pl={Icon ? "50px" : 0}>
              <TrendIndicator trend={trend} higherIsBetter={higherIsBetter} isApproximate={trend.is_approximate} dense />
            </Box>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card
      variant="outlined"
      sx={(theme) => {
        const dark = theme.palette.mode === "dark";
        return {
          flex: "1 1 220px",
          position: "relative",
          transition: "transform 220ms ease, box-shadow 220ms ease",
          ...(hero && color
            ? {
                backgroundImage: `linear-gradient(135deg, ${color}${dark ? "2E" : "1C"} 0%, transparent 65%)`,
              }
            : {}),
          "&:hover": {
            transform: "translateY(-3px)",
            boxShadow: CARD_SHADOW_HOVER[dark ? "dark" : "light"],
          },
        };
      }}
    >
      <CardContent>
        <Stack direction="row" spacing={1.5} alignItems="flex-start">
          {Icon && (
            <Box
              sx={{
                width: 40,
                height: 40,
                borderRadius: "50%",
                bgcolor: color ? `${color}1A` : "action.selected",
                color: badgeColor,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <Icon fontSize="small" />
            </Box>
          )}
          <Box sx={{ minWidth: 0, flexGrow: 1 }}>
            <Typography variant="body2" color="text.secondary">
              {label}
            </Typography>
            {/* Tight vertical rhythm: value, then the delta line, then the "vs" caption
                directly under it -- no extra air between the three. */}
            {/* MUI's h3 default is 3rem/fontWeight 300 -- knocked down to 1.75rem (28px)
                and bolded so the number stays clearly the card's focal point without
                dwarfing the delta/sparkline below it. Explicit here (not left to the
                default) so all 6 cards render identically regardless of how long their
                particular value's string happens to be. */}
            <Typography variant="h3" sx={{ lineHeight: 1.15, fontSize: "1.75rem", fontWeight: 700 }}>
              {value}
            </Typography>
            {trend && (
              <Box mt={0.5}>
                <TrendIndicator trend={trend} higherIsBetter={higherIsBetter} isApproximate={trend.is_approximate} />
              </Box>
            )}
          </Box>
        </Stack>
        {trend && (
          <Box sx={{ mt: 1.5, height: 36 }}>
            <Sparkline series={trend.series} color={color || "#2a78d6"} formatValue={formatSparklineValue} />
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
