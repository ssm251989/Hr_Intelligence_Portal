import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import { useTheme } from "@mui/material/styles";

import { FRESH } from "../theme/tokens";
import { useReducedMotion } from "./motion";

// Part 15 B: small Lottie animations stored locally (src/assets/lottie/, made by
// scripts/make-lottie.mjs): success tick, confetti, waving hand, loader, empty box, rocket.
// lottie-react is lazy-loaded. Default theme colours inside the files are swapped for the
// company's theme; under reduced motion the final frame is shown still.

// Only the svg renderer is needed -- LottieSvg carries the smaller engine build.
const Lottie = lazy(() => import("lottie-react").then((m) => ({ default: m.LottieSvg })));
const FILES = import.meta.glob("../assets/lottie/*.json", { import: "default" }) as Record<string, () => Promise<object>>;

export type AnimationName = "success" | "confetti" | "wave" | "loader" | "empty-box" | "rocket";
const LOOPS: Record<AnimationName, boolean> = { success: false, confetti: false, wave: true, loader: true, "empty-box": true, rocket: true };

const toRgb = (hex: string) => [1, 3, 5].map((i) => Math.round((parseInt(hex.slice(i, i + 2), 16) / 255) * 1000) / 1000);

function recolour(data: object, swaps: [number[], number[]][]): object {
  const json = JSON.stringify(data);
  // Colours are stored as [r,g,b,1] arrays; swap exact default values only.
  return JSON.parse(
    swaps.reduce((acc, [from, to]) => acc.split(JSON.stringify([...from, 1])).join(JSON.stringify([...to, 1])), json),
  );
}

export default function FriendlyAnimation({ name, size = 120, loop, label }: { name: AnimationName; size?: number; loop?: boolean; label?: string }) {
  const theme = useTheme();
  const t = theme.palette.fresh;
  const reduced = useReducedMotion();
  const [raw, setRaw] = useState<object | null>(null);

  useEffect(() => {
    let alive = true;
    FILES[`../assets/lottie/${name}.json`]?.().then((d) => alive && setRaw(d));
    return () => {
      alive = false;
    };
  }, [name]);

  const data = useMemo(() => {
    if (!raw) return null;
    const base = FRESH.light;
    return recolour(raw, [
      [toRgb(base.brand), toRgb(t.brand)], [toRgb(base.coral), toRgb(t.coral)], [toRgb(base.sun), toRgb(t.sun)],
      [toRgb(base.sky), toRgb(t.sky)], [toRgb(base.brandSoft), toRgb(t.brandSoft)], [toRgb(base.line), toRgb(t.line)],
    ]);
  }, [raw, t]);

  const lastFrame = (data as { op?: number } | null)?.op ?? 1;
  const box = { width: size, height: size, display: "grid", placeItems: "center", flexShrink: 0 };
  return (
    <Box role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true} sx={box}>
      {data && (
        <Suspense fallback={null}>
          <Lottie
            src={data}
            loop={reduced ? false : loop ?? LOOPS[name]}
            autoplay
            // Reduced motion: play only the final frame, i.e. a still picture.
            segment={reduced ? [Math.max(0, lastFrame - 1), lastFrame] : undefined}
            style={{ width: size, height: size }}
          />
        </Suspense>
      )}
    </Box>
  );
}
