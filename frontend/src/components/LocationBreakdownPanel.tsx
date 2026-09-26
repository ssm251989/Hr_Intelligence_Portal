import { useMemo, useState } from "react";
import Box from "@mui/material/Box";
import FormControl from "@mui/material/FormControl";
import Grid from "@mui/material/Grid";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { LabeledCount } from "../api/types";
import BreakdownLegend, { toBreakdownSlices } from "./BreakdownLegend";
import { lazy, Suspense } from "react";

const PlacesMap = lazy(() => import("./maps/PlacesMap"));

const ALL_LOCATIONS = "all";

export default function LocationBreakdownPanel({ rows }: { rows: LabeledCount[] }) {
  const [selected, setSelected] = useState(ALL_LOCATIONS);
  const options = useMemo(() => [...rows].map((row) => row.label).sort(), [rows]);
  const filteredRows = selected === ALL_LOCATIONS ? rows : rows.filter((row) => row.label === selected);
  const slices = toBreakdownSlices(filteredRows);
  const total = slices.reduce((sum, row) => sum + row.count, 0);

  return (
    <Box>
      <Stack direction="row" alignItems="center" justifyContent="space-between" mb={2} flexWrap="wrap" gap={1}>
        <Typography variant="h6">Jobs by Location</Typography>
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel id="location-breakdown-filter-label">Location</InputLabel>
          <Select
            labelId="location-breakdown-filter-label"
            label="Location"
            value={selected}
            onChange={(event: SelectChangeEvent) => setSelected(event.target.value)}
          >
            <MenuItem value={ALL_LOCATIONS}>All Locations</MenuItem>
            {options.map((location) => (
              <MenuItem key={location} value={location}>
                {location}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>
      {/* Map answers "where" via bubble size; the legend list is the table-view
          equivalent of that same filtered data -- replaces the donut this panel used to
          pair with the map, since the legend already carries the count/percentage the
          donut existed for. Side-by-side, matching Department/Status Overview's
          chart-left/legend-right layout, now that the sidebar-width trims free enough
          room at this panel's actual (2-up-then-1, or 3-up on wide screens) width. */}
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 7 }}>
          <Suspense fallback={null}><PlacesMap kind="jobs" height={280} /></Suspense>
        </Grid>
        <Grid size={{ xs: 12, md: 5 }}>
          <BreakdownLegend slices={slices} total={total} />
        </Grid>
      </Grid>
    </Box>
  );
}
