import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { useT } from "../../i18n";
import { Emoji, InfoTip, useReducedMotion } from "../../ui-kit";
import { useFresh } from "./shared";

// F7: budget meter -- how much of the pool the proposals use. Coral + words when over.
export default function BudgetMeter({ title, tip, used, pool, money }: { title: string; tip: string; used: number; pool: number; money: (v: number) => string }) {
  const t = useT();
  const f = useFresh();
  const reduced = useReducedMotion();
  const pct = pool > 0 ? (used / pool) * 100 : used > 0 ? 100 : 0;
  const over = pool > 0 ? used > pool : false;
  const near = !over && pct >= 90;
  const colour = over ? f.coral : near ? f.sun : f.brand;
  const words =
    pool <= 0
      ? t("compensation.budget.no_pool", { used: money(used) })
      : over
        ? t("compensation.budget.over", { amount: money(used - pool), used: money(used), pool: money(pool) })
        : t("compensation.budget.left", { amount: money(pool - used), used: money(used), pool: money(pool) });
  return (
    <Box sx={{ p: 2, borderRadius: "14px", bgcolor: over ? f.coralSoft : f.surface2, border: `1px solid ${over ? f.coral : f.line}` }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <Emoji name={over ? "fire" : near ? "warning" : "money"} size={18} />
        <Typography sx={{ fontWeight: 800, flex: 1 }}>
          {title}
          <InfoTip text={tip} />
        </Typography>
        <Typography sx={{ fontWeight: 800, color: over ? f.coral : f.ink, fontVariantNumeric: "tabular-nums" }}>{pool > 0 ? `${Math.round(pct)}%` : "—"}</Typography>
      </Stack>
      <Box
        role="meter"
        aria-valuemin={0}
        aria-valuemax={Math.max(pool, used)}
        aria-valuenow={used}
        aria-valuetext={words}
        aria-label={title}
        sx={{ position: "relative", height: 12, borderRadius: 999, bgcolor: f.line, overflow: "hidden" }}
      >
        <Box sx={{ width: `${Math.min(100, pct)}%`, height: "100%", bgcolor: colour, borderRadius: 999, transition: reduced ? undefined : "width 400ms ease" }} />
      </Box>
      <Typography sx={{ mt: 1, fontSize: 13, fontWeight: over ? 700 : 500, color: over ? f.coral : f.muted }}>{words}</Typography>
    </Box>
  );
}
