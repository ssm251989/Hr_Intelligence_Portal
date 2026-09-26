import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import type { SxProps, Theme } from "@mui/material/styles";

// Part 16.1: the 12-column page grid. Cards stretch to fill their row at every width;
// on phones every cell takes the full row.
//   <PageGrid><Cell span={8}>...</Cell><Cell span={4}>...</Cell></PageGrid>

type Span = number | { xs?: number; sm?: number; md?: number; lg?: number; xl?: number };

export function PageGrid({ children, gap = 2.25, sx }: { children: ReactNode; gap?: number; sx?: SxProps<Theme> }) {
  return (
    <Box sx={{ display: "grid", gridTemplateColumns: "repeat(12, minmax(0, 1fr))", gap, alignItems: "stretch", ...sx }}>
      {children}
    </Box>
  );
}

export function Cell({ span = 12, children, sx }: { span?: Span; children: ReactNode; sx?: SxProps<Theme> }) {
  const s = typeof span === "number" ? { xs: 12, md: span } : { xs: 12, ...span };
  const gridColumn = Object.fromEntries(Object.entries(s).map(([bp, n]) => [bp, `span ${n}`]));
  return <Box sx={{ gridColumn, minWidth: 0, display: "flex", flexDirection: "column", "& > *": { flex: 1 }, ...sx }}>{children}</Box>;
}
