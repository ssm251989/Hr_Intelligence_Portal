import Box from "@mui/material/Box";

// One emoji vocabulary for the whole app (Part 15 B). Components ask for a NAME, never a
// raw character, so the rendering (native glyph now, local Fluent SVG assets in the visual
// kit) can change in one place.
export const EMOJI: Record<string, string> = {
  house: "🏠", check: "✅", briefcase: "💼", technologist: "🧑‍💻", magnifier: "🔎", star: "⭐",
  calendar: "📅", inbox: "📥", money: "💰", shield: "🛡️", envelope: "📨", bar_chart: "📊",
  waving_hand: "👋", target: "🎯", ring_buoy: "🛟", laptop: "💻", door: "🚪", people: "👥",
  gear: "⚙️", rocket: "🚀", bell: "🔔", puzzle: "🧩",
};

export default function Emoji({ name, size = 18, label }: { name: string; size?: number; label?: string }) {
  const char = EMOJI[name] ?? EMOJI.puzzle;
  return (
    <Box
      component="span"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      sx={{ display: "inline-grid", placeItems: "center", width: size + 4, fontSize: size, lineHeight: 1, flexShrink: 0 }}
    >
      {char}
    </Box>
  );
}
