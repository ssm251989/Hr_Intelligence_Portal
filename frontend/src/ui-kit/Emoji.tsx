import Box from "@mui/material/Box";

// One emoji vocabulary for the whole app (Part 15 B): Microsoft Fluent Emoji (MIT, flat
// style) stored locally in src/assets/emoji/ so they look identical on Windows, Mac and
// phones. Components ask for a NAME, never a raw character. Unknown names fall back to
// the native glyph (if listed below) and then to the puzzle piece.

const FILES = import.meta.glob("../assets/emoji/*.svg", { eager: true, query: "?url", import: "default" }) as Record<string, string>;
const URLS: Record<string, string> = Object.fromEntries(
  Object.entries(FILES).map(([path, url]) => [path.split("/").pop()!.replace(/\.svg$/, ""), url]),
);

// Native fallbacks (and the words screen readers get when an emoji carries meaning).
export const EMOJI: Record<string, string> = {
  house: "🏠", check: "✅", briefcase: "💼", technologist: "🧑‍💻", magnifier: "🔎", star: "⭐",
  calendar: "🗓️", inbox: "📥", money: "💰", shield: "🛡️", envelope: "📨", bar_chart: "📊",
  waving_hand: "👋", target: "🎯", ring_buoy: "🛟", laptop: "💻", door: "🚪", people: "👥",
  gear: "⚙️", rocket: "🚀", bell: "🔔", puzzle: "🧩", alarm_clock: "⏰", fire: "🔥", new: "🆕",
  pause: "⏸️", party: "🎉", writing_hand: "✍️", speaking_head: "🗣️", page: "📄", compass: "🧭",
  glowing_star: "🌟", robot: "🤖", memo: "📝", id_card: "🪪", graduation: "🎓", bank: "🏦",
  camera: "📸", question: "❓", coffee: "☕", bento: "🍱", sparkles: "✨", speech: "💬", smile: "😊",
  pin: "📍", label: "🏷️", warning: "⚠️", lock: "🔒", clipboard: "📋", hourglass: "⏳", thumbs_up: "👍",
  chart_up: "📈", chart_down: "📉", building: "🏢", key: "🔑", globe: "🌐", link: "🔗", confused: "😕",
  tools: "🛠️", seedling: "🌱", trophy: "🏆", handshake: "🤝", clapper: "🎬", package: "📦", cross: "❌",
  eyes: "👀", pencil: "✏️", cake: "🎂", light_bulb: "💡", mail: "📧", file_folder: "📁", magic: "🪄",
  thinking: "🤔", tada_face: "🥳", world_map: "🗺️",
};

export function hasEmoji(name: string): boolean {
  return Boolean(URLS[name] || EMOJI[name]);
}

export default function Emoji({ name, size = 18, label }: { name: string; size?: number; label?: string }) {
  const url = URLS[name];
  const a11y = label ? { role: "img", "aria-label": label } : { "aria-hidden": true };
  if (url) {
    return (
      <Box component="img" src={url} alt={label ?? ""} width={size} height={size} draggable={false} {...(label ? {} : { "aria-hidden": true })}
        sx={{ display: "inline-block", width: size, height: size, flexShrink: 0, verticalAlign: "middle", userSelect: "none" }} />
    );
  }
  return (
    <Box component="span" {...a11y} sx={{ display: "inline-grid", placeItems: "center", width: size, height: size, fontSize: size * 0.9, lineHeight: 1, flexShrink: 0 }}>
      {EMOJI[name] ?? EMOJI.puzzle}
    </Box>
  );
}
