import Avatar from "@mui/material/Avatar";
import type { SxProps, Theme } from "@mui/material/styles";

import type { UUID } from "../api/types";
import { initials } from "../utils/avatar";
import { useCandidatePhotoUrl } from "../utils/photo";

// Extracted into its own component (rather than inlined at each call site) because
// useCandidatePhotoUrl is a hook -- it can't be called directly inside the .map() callbacks
// that render Recent Candidates / Candidates List rows, only from a real component.
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

  return (
    <Avatar src={photoUrl ?? undefined} sx={{ bgcolor: "primary.main", ...sx }}>
      {initials(name || email || "?")}
    </Avatar>
  );
}
