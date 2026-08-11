import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import { candidateSourceIcon, candidateSourceIconColor } from "../utils/candidateSourceIcons";

// Icon-only badge for a Source column -- no text label, shared between the Candidates
// List page and the Candidates Dashboard's Recent Candidates panel so the two never
// drift out of sync. Wrapped in a Tooltip so the source name is still discoverable on
// hover; "manual" isn't one of the four real sourcing platforms this was originally
// built for (Career Portal, Local Import, LinkedIn, Naukri) but shares the same
// icon-badge treatment for visual consistency across every row.
export default function SourceIcon({ source }: { source: string }) {
  const Icon = candidateSourceIcon(source);
  const color = candidateSourceIconColor(source);
  if (!Icon) {
    return (
      <Tooltip title={source}>
        <Typography variant="body2" color="text.secondary">
          —
        </Typography>
      </Tooltip>
    );
  }
  return (
    <Tooltip title={source.replace(/_/g, " ")}>
      <Icon fontSize="small" sx={{ color: color ?? "action.active" }} />
    </Tooltip>
  );
}
