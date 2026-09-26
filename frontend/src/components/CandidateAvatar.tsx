import Avatar from "@mui/material/Avatar";
import type { SxProps, Theme } from "@mui/material/styles";

import type { UUID } from "../api/types";
import { initials } from "../utils/avatar";
import { useCandidatePhotoUrl } from "../utils/photo";
import { useFresh } from "./candidates/stages";

// Extracted into its own component (rather than inlined at each call site) because
// useCandidatePhotoUrl is a hook -- it can't be called directly inside the .map() callbacks
// that render Recent Candidates / Candidates List rows, only from a real component.
// Part 15.4: real photo if there is one, else a coloured initials tile (same colour for the
// same name every time, like ui-kit UserAvatar).
export default function CandidateAvatar({
  candidateId,
  photoPath,
  name,
  email,
  sx,
}: {
  candidateId: UUID;
  photoPath: string | null | undefined;
  name: string | null | undefined;
  email: string | null | undefined;
  sx?: SxProps<Theme>;
}) {
  const photoUrl = useCandidatePhotoUrl(candidateId, photoPath);
  const f = useFresh();
  const label = name || email || "?";
  const tiles = [
    [f.skySoft, f.sky], [f.brandSoft, f.brand], [f.sunSoft, f.sunInk], [f.coralSoft, f.coral], [f.okSoft, f.ok],
  ];
  const hash = [...label].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
  const [bg, fg] = tiles[hash % tiles.length];

  return (
    <Avatar
      src={photoUrl ?? undefined}
      alt={name || email || undefined}
      variant="rounded"
      sx={{ bgcolor: bg, color: fg, fontWeight: 800, borderRadius: "30%", ...(sx as object) }}
    >
      {initials(label)}
    </Avatar>
  );
}
