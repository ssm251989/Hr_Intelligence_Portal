import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import { useTheme } from "@mui/material/styles";

import { useReducedMotion } from "./motion";

// Part 15 B: the mockup's score/readiness ring (conic gradient), filling up on first show.
export default function ProgressRing({
  value, size = 110, thickness = 13, label, caption, tone = "brand",
}: {
  value: number; // 0-100
  size?: number;
  thickness?: number;
  /** What sits in the middle (defaults to the number). */
  label?: string;
  /** Screen-reader description, e.g. "Match score 82 out of 100". */
  caption: string;
  tone?: "brand" | "sun" | "coral" | "ok" | "sky";
}) {
  const t = useTheme().palette.fresh;
  const reduced = useReducedMotion();
  const target = Math.max(0, Math.min(100, Math.round(value)));
  const [shown, setShown] = useState(reduced ? target : 0);

  useEffect(() => {
    if (reduced) {
      setShown(target);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / 900);
      setShown(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, reduced]);

  const colour = t[tone];
  return (
    <Box
      role="img"
      aria-label={caption}
      sx={{ width: size, height: size, borderRadius: "50%", flexShrink: 0, display: "grid", placeItems: "center", background: `conic-gradient(${colour} ${shown}%, ${t.line} 0)` }}
    >
      <Box sx={{ width: size - thickness * 2, height: size - thickness * 2, borderRadius: "50%", bgcolor: t.surface, display: "grid", placeItems: "center", fontWeight: 800, fontSize: Math.round(size * 0.24), fontVariantNumeric: "tabular-nums" }}>
        {label ?? shown}
      </Box>
    </Box>
  );
}
