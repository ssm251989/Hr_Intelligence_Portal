import Avatar from "@mui/material/Avatar";
import { useTheme } from "@mui/material/styles";

import { initials } from "../utils/avatar";

// Part 15 B: real photo if there is one, otherwise a coloured initials tile. The colour is
// picked from the name so the same person always gets the same tile.
export default function UserAvatar({ name, src, size = 40, square = true }: { name: string; src?: string | null; size?: number; square?: boolean }) {
  const t = useTheme().palette.fresh;
  const tiles = [
    [t.skySoft, t.sky], [t.brandSoft, t.brand], [t.sunSoft, t.sunInk], [t.coralSoft, t.coral], [t.okSoft, t.ok],
  ];
  const hash = [...(name || "?")].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
  const [bg, fg] = tiles[hash % tiles.length];
  return (
    <Avatar
      src={src ?? undefined}
      alt={name}
      variant={square ? "rounded" : "circular"}
      sx={{ width: size, height: size, bgcolor: bg, color: fg, fontWeight: 800, fontSize: Math.round(size * 0.36), borderRadius: square ? `${Math.round(size * 0.31)}px` : "50%" }}
    >
      {initials(name || "?")}
    </Avatar>
  );
}
