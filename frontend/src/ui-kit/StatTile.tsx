import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import Emoji from "./Emoji";
import { useToneColours, type Tone } from "./StatusChip";

// Part 15 C: a number is never alone -- big figure + the word that says what it counts
// ("12" + "Open jobs"), with an optional trend line ("▲ 2 this week").
export default function StatTile({
  emoji, value, label, trend, trendDirection = "up", tone = "brand", to, loading,
}: {
  emoji: string;
  value: number | string;
  label: string;
  trend?: string;
  /** "up" = good news (green), "down" = needs attention (coral), "flat" = neutral. */
  trendDirection?: "up" | "down" | "flat";
  tone?: Tone;
  to?: string;
  loading?: boolean;
}) {
  const t = useTheme().palette.fresh;
  const { bg } = useToneColours(tone);
  const trendColour = trendDirection === "up" ? t.ok : trendDirection === "down" ? t.coral : t.muted;
  const arrow = trendDirection === "up" ? "▲" : trendDirection === "down" ? "▼" : "•";
  const body = (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 0.75, p: 2.25 }}>
      <Box sx={{ width: 42, height: 42, borderRadius: "12px", bgcolor: bg, display: "grid", placeItems: "center" }}>
        <Emoji name={emoji} size={22} />
      </Box>
      <Typography component="b" sx={{ fontSize: 28, fontWeight: 800, lineHeight: 1, fontVariantNumeric: "tabular-nums", mt: 0.5 }}>
        {loading ? "…" : typeof value === "number" ? value.toLocaleString() : value}
      </Typography>
      <Typography sx={{ color: t.muted, fontWeight: 500 }}>{label}</Typography>
      {trend && (
        <Typography sx={{ fontSize: 12, fontWeight: 700, color: trendColour }}>
          {arrow} {trend}
        </Typography>
      )}
    </Box>
  );
  return (
    <Card
      {...(to ? { component: RouterLink, to } : {})}
      aria-label={`${value} ${label}${trend ? `, ${trend}` : ""}`}
      sx={{
        textDecoration: "none", color: "inherit", display: "block", height: "100%",
        ...(to ? { transition: "box-shadow 200ms ease, transform 200ms ease", "&:hover": { boxShadow: t.shadowHover, transform: "translateY(-2px)" } } : {}),
      }}
    >
      {body}
    </Card>
  );
}
