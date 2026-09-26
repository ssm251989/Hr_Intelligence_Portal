import type { StatTrend } from "../../api/types";
import type { TFunction } from "../../i18n";
import { formatMonthKey } from "../../utils/datetime";

/** StatCard's month-on-month trend, as the words + direction StatTile shows. */
export function trendProps(trend: StatTrend | null | undefined, t: TFunction, higherIsBetter = true): { trend?: string; trendDirection?: "up" | "down" | "flat" } {
  if (!trend) return {};
  const month = formatMonthKey(trend.compare_month);
  const pct = trend.pct_change == null && trend.compare_value === 0 ? 100 : trend.pct_change;
  if (pct == null) return { trend: t("screening.trend.none", { month }), trendDirection: "flat" };
  if (pct === 0) return { trend: t("screening.trend.same", { month }), trendDirection: "flat" };
  const good = (pct > 0) === higherIsBetter;
  return {
    trend: t(pct > 0 ? "screening.trend.up" : "screening.trend.down", { pct: Math.abs(Math.round(pct * 10) / 10), month }),
    trendDirection: good ? "up" : "down",
  };
}
