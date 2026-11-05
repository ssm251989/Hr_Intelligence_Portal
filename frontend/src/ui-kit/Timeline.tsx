import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import Emoji from "./Emoji";

export interface TimelineItem {
  id: string;
  emoji: string;
  title: ReactNode;
  meta?: ReactNode; // when + detail, e.g. "Today 10:12 · undo until 2:12 pm"
}

// Part 15 B: activity timeline (mockup "Activity" card): emoji tile + bold line + muted meta.
export default function Timeline({ items, empty = "Nothing has happened here yet." }: { items: TimelineItem[]; empty?: ReactNode }) {
  const t = useTheme().palette.fresh;
  if (!items.length) return <Typography sx={{ color: t.muted }}>{empty}</Typography>;
  return (
    <Box component="ol" sx={{ listStyle: "none", m: 0, p: 0, display: "flex", flexDirection: "column", gap: 1.75 }}>
      {items.map((i) => (
        <Box component="li" key={i.id} sx={{ display: "flex", gap: 1.5 }}>
          <Box sx={{ width: 34, height: 34, borderRadius: "11px", display: "grid", placeItems: "center", flexShrink: 0, bgcolor: t.surface2, border: `1px solid ${t.line}` }}>
            <Emoji name={i.emoji} size={18} />
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontWeight: 600 }}>{i.title}</Typography>
            {i.meta && <Typography sx={{ fontSize: 12, color: t.muted }}>{i.meta}</Typography>}
          </Box>
        </Box>
      ))}
    </Box>
  );
}
