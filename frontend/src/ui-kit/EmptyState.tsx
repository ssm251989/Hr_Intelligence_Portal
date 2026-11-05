import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import Illustration, { type IllustrationName } from "./Illustration";

// Part 15 C: every empty list/state = illustration + ONE sentence + the button that fixes it.
//   <EmptyState illustration="hiring" title="No jobs yet." action={<Button ...>＋ Create your first job</Button>} />
export default function EmptyState({
  illustration = "empty", title, hint, action, compact,
}: {
  illustration?: IllustrationName;
  title: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}) {
  const t = useTheme().palette.fresh;
  return (
    <Box role="status" sx={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 1.5, py: compact ? 3 : 5, px: 2 }}>
      <Illustration name={illustration} height={compact ? 96 : 150} />
      <Typography sx={{ fontWeight: 700, fontSize: compact ? 15 : 17, mt: 1 }}>{title}</Typography>
      {hint && <Typography sx={{ color: t.muted, maxWidth: "52ch" }}>{hint}</Typography>}
      {action && <Box sx={{ mt: 0.5 }}>{action}</Box>}
    </Box>
  );
}
