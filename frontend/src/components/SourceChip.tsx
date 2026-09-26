import type { ChipProps } from "@mui/material/Chip";

import { candidateSourceLabel } from "../api/types";
import StatusChip from "../ui-kit/StatusChip";
import type { Tone } from "../ui-kit/StatusChip";

// backend/app/models/candidate.py CANDIDATE_SOURCES. Part 15.4: a pill in the friendly kit
// look (colour + emoji + word). The five sourcing-integration values
// (linkedin/naukri/indeed/monster/shine) are defined but never written yet, so they share a
// neutral style.
const SOURCE_STYLE: Record<string, { tone: Tone; emoji: string }> = {
  career_portal: { tone: "sky", emoji: "globe" },
  manual: { tone: "muted", emoji: "inbox" },
  local_import: { tone: "brand", emoji: "file_folder" },
};

export default function SourceChip({ source, size = "small" }: { source: string; size?: ChipProps["size"] }) {
  const style = SOURCE_STYLE[source] ?? { tone: "muted" as Tone, emoji: "link" };
  return <StatusChip tone={style.tone} emoji={style.emoji} label={candidateSourceLabel(source)} size={size === "medium" ? "medium" : "small"} />;
}
