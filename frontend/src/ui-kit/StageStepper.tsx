import Box from "@mui/material/Box";
import { useTheme } from "@mui/material/styles";

// Part 15 B: the mockup's segmented stage bar -- done segments in brand, the current one a
// brand->sun gradient, the rest grey, with the stage names underneath.
export default function StageStepper({ stages, current, compact }: { stages: string[]; current: number; compact?: boolean }) {
  const t = useTheme().palette.fresh;
  return (
    <Box role="progressbar" aria-valuemin={1} aria-valuemax={stages.length} aria-valuenow={current + 1} aria-valuetext={`Stage ${current + 1} of ${stages.length}: ${stages[current] ?? ""}`}>
      <Box sx={{ display: "flex", gap: 0.5 }}>
        {stages.map((s, i) => (
          <Box key={s} sx={{
            flex: 1, height: 8, borderRadius: 4,
            background: i < current ? t.brand : i === current ? `linear-gradient(90deg, ${t.brand}, ${t.sun})` : t.line,
          }} />
        ))}
      </Box>
      {!compact && (
        <Box sx={{ display: "flex", justifyContent: "space-between", gap: 0.5, mt: 0.75, fontSize: 11, color: t.muted }}>
          {stages.map((s, i) => (
            <Box component="span" key={s} sx={{ fontWeight: i === current ? 700 : 500, color: i === current ? t.ink : undefined, textAlign: "center", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {s}
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
}
