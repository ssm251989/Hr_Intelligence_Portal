import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import Emoji from "./Emoji";
import PageTour from "./PageTour";
import ShowMeHow from "./ShowMeHow";

// Part 15 C: every page answers "what is this page?" and "what do I do next?" --
// emoji + title + ONE line saying what you can do here + ONE primary button (top-right).
// Secondary actions go in `extra` (ghost buttons) and stay visually quieter.
export default function PageHeader({
  emoji, title, purpose, primary, extra, tourKey, below,
}: {
  emoji: string;
  title: ReactNode;
  purpose: ReactNode;
  primary?: ReactNode;
  extra?: ReactNode;
  /** Media/tour key for the "Show me how" button, e.g. "jobs". */
  tourKey?: string;
  below?: ReactNode;
}) {
  const t = useTheme().palette.fresh;
  return (
    <Box component="header" sx={{ mb: 2.5 }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ xs: "flex-start", sm: "center" }} justifyContent="space-between">
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minWidth: 0 }}>
          <Box sx={{ width: 48, height: 48, borderRadius: "14px", bgcolor: t.brandSoft, display: "grid", placeItems: "center", flexShrink: 0 }}>
            <Emoji name={emoji} size={26} />
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="h1" component="h1" data-tour="page-title">{title}</Typography>
            <Typography sx={{ color: t.muted, mt: 0.5, maxWidth: "70ch" }}>{purpose}</Typography>
          </Box>
        </Stack>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ flexShrink: 0, flexWrap: "wrap", rowGap: 1 }}>
          {tourKey && <ShowMeHow tourKey={tourKey} />}
          {extra}
          {primary && <Box data-tour="page-primary" sx={{ display: "inline-flex" }}>{primary}</Box>}
        </Stack>
      </Stack>
      {below && <Box sx={{ mt: 2 }}>{below}</Box>}
      {tourKey && <PageTour tourKey={tourKey} />}
    </Box>
  );
}
