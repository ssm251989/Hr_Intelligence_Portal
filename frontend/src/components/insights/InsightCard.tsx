import { useCallback, useEffect, useState, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { ApiError } from "../../api/client";
import { Emoji, InfoTip } from "../../ui-kit";

// Part 15.6: the card every Insights page uses -- emoji + title + one quiet line + body.

export function InsightCard({ title, sub, emoji, help, action, children, dataTour }: {
  title: string; sub?: string; emoji?: string; help?: string; action?: ReactNode; children: ReactNode; dataTour?: string;
}) {
  const f = useTheme().palette.fresh;
  return (
    <Card component="section" data-tour={dataTour} sx={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ px: 2.25, pt: 2, pb: 1 }}>
        {emoji && <Emoji name={emoji} size={18} />}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography component="h2" sx={{ fontWeight: 800, fontSize: 16 }}>
            {title}
            {help && <InfoTip text={help} />}
          </Typography>
          {sub && <Typography sx={{ color: f.muted, fontSize: 13 }}>{sub}</Typography>}
        </Box>
        {action}
      </Stack>
      <Box sx={{ px: 2.25, pb: 2.25, flex: 1, minHeight: 0 }}>{children}</Box>
    </Card>
  );
}

export function CardLoading({ height = 220 }: { height?: number }) {
  return <Skeleton variant="rounded" height={height} />;
}

export type Loaded<T> = { state: "loading" } | { state: "ok"; data: T } | { state: "forbidden" } | { state: "error"; error: unknown };

/** Load once (and on reload()). A 403 becomes "forbidden" so the page can quietly hide that card. */
export function useLoaded<T>(fn: () => Promise<T>): [Loaded<T>, () => void] {
  const [value, setValue] = useState<Loaded<T>>({ state: "loading" });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setValue({ state: "loading" });
    fn()
      .then((data) => live && setValue({ state: "ok", data }))
      .catch((error) => live && setValue(error instanceof ApiError && error.status === 403 ? { state: "forbidden" } : { state: "error", error }));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  return [value, reload];
}

/** "hiring_funnel" -> "Hiring funnel" when the server gave no label. */
export function friendly(code: string, label?: string | null): string {
  if (label && label !== code) return label;
  const words = code.replace(/[_.-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : code;
}
