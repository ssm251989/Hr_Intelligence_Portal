import { useMemo, useState } from "react";
import Box from "@mui/material/Box";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { LabeledCount } from "../api/types";
import LabeledDonutChart from "./LabeledDonutChart";

const ALL_DEPARTMENTS = "all";

export default function DepartmentBreakdownPanel({ rows }: { rows: LabeledCount[] }) {
  const [selected, setSelected] = useState(ALL_DEPARTMENTS);
  const options = useMemo(() => [...rows].map((row) => row.label).sort(), [rows]);
  // A single-department selection reduces the donut to that one slice -- which is
  // trivially 100% of the filtered set, the same result "recalculate percentages
  // against the filtered set" gives generally. Implemented as one rule (filter rows,
  // let the existing total-relative percentage math do the rest) rather than special-
  // casing "exactly one selected" as a distinct "show 100%" mode.
  const filteredRows = selected === ALL_DEPARTMENTS ? rows : rows.filter((row) => row.label === selected);

  return (
    <Box>
      <Stack direction="row" alignItems="center" justifyContent="space-between" mb={2} flexWrap="wrap" gap={1}>
        <Typography variant="h6">Jobs by Department</Typography>
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel id="department-breakdown-filter-label">Department</InputLabel>
          <Select
            labelId="department-breakdown-filter-label"
            label="Department"
            value={selected}
            onChange={(event: SelectChangeEvent) => setSelected(event.target.value)}
          >
            <MenuItem value={ALL_DEPARTMENTS}>All Departments</MenuItem>
            {options.map((department) => (
              <MenuItem key={department} value={department}>
                {department}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>
      <LabeledDonutChart title="" rows={filteredRows} />
    </Box>
  );
}
