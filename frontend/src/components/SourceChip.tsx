import Chip from "@mui/material/Chip";
import type { ChipProps } from "@mui/material/Chip";

import { candidateSourceLabel } from "../api/types";

type SourceColor = "info" | "default" | "primary";

// backend/app/models/candidate.py CANDIDATE_SOURCES. The five sourcing-integration
// values (linkedin/naukri/indeed/monster/shine) are defined but never written yet, so
// they share a neutral color with everything else not yet distinguished.
const SOURCE_COLOR_MAP: Record<string, SourceColor> = {
  career_portal: "info",
  manual: "default",
  csv_import: "primary",
};

export default function SourceChip({ source, size = "small" }: { source: string; size?: ChipProps["size"] }) {
  return (
    <Chip
      label={candidateSourceLabel(source)}
      color={SOURCE_COLOR_MAP[source] ?? "default"}
      size={size}
      variant="outlined"
    />
  );
}
