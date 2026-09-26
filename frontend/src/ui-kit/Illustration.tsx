import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import type { SxProps, Theme } from "@mui/material/styles";

// Part 15 B: unDraw illustrations (free licence), recoloured to the theme by
// scripts/recolor-illustrations.mjs. Rendered INLINE so their accent (`currentColor`) and
// neutrals (var(--line) ...) follow the company's brand and light/dark mode. Each file is
// its own lazy chunk -- a page only downloads the drawings it shows.

const LOADERS = import.meta.glob("../assets/ill/*.svg", { query: "?raw", import: "default" }) as Record<string, () => Promise<string>>;

export type IllustrationName =
  | "hello" | "welcome-aboard" | "empty" | "no-data" | "void" | "page-not-found" | "server-down" | "warning" | "access-denied"
  | "secure-login" | "setup-wizard" | "completed-steps" | "completed-tasks" | "done" | "success" | "celebration" | "hiring"
  | "interview" | "calendar" | "search" | "people-search" | "team-spirit" | "meet-the-team" | "onboarding" | "job-offers"
  | "contract-signed" | "resume" | "goals" | "target" | "to-do-list" | "helpful-sign" | "devices" | "report" | "data-reports"
  | "analytics" | "mailbox" | "empty-mailbox" | "settings" | "fill-forms" | "upload-image" | "files-uploading" | "coffee-time"
  | "video-tutorial" | "location-search" | "map" | "order-confirmed" | "signed-document" | "personal-information" | "work-in-progress";

const cache = new Map<string, string>();

export default function Illustration({ name, height = 160, tone = "brand", sx }: { name: IllustrationName; height?: number; tone?: "brand" | "coral" | "sun" | "sky"; sx?: SxProps<Theme> }) {
  const key = `../assets/ill/${name}.svg`;
  const [svg, setSvg] = useState<string | null>(cache.get(key) ?? null);

  useEffect(() => {
    if (cache.has(key)) {
      setSvg(cache.get(key)!);
      return;
    }
    let alive = true;
    LOADERS[key]?.().then((raw) => {
      cache.set(key, raw);
      if (alive) setSvg(raw);
    });
    return () => {
      alive = false;
    };
  }, [key]);

  return (
    <Box
      aria-hidden
      sx={[
        (theme) => ({
          height, width: "100%", maxWidth: height * 1.7, color: theme.palette.fresh[tone], display: "grid", placeItems: "center", flexShrink: 0,
          "& svg": { width: "100%", height: "100%", display: "block" },
        }),
        ...(Array.isArray(sx) ? sx : [sx]),
      ]}
      // Local, build-time asset from src/assets/ill -- never user-supplied markup.
      dangerouslySetInnerHTML={svg ? { __html: svg } : undefined}
    />
  );
}
