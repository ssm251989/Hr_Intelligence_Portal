import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import type { TopJobItem } from "../api/types";
import { useT } from "../i18n";
import { EmptyState } from "../ui-kit";

export default function TopPerformingJobs({ jobs }: { jobs: TopJobItem[] }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  if (jobs.length === 0) {
    return <EmptyState compact illustration="no-data" title={t("jobs.top.empty")} />;
  }

  const maxCount = Math.max(...jobs.map((job) => job.application_count), 1);

  return (
    <Stack component="ol" spacing={1.25} sx={{ listStyle: "none", m: 0, p: 0 }}>
      {jobs.map((job, index) => (
        <Stack component="li" key={job.job_id} direction="row" spacing={1.5} alignItems="center"
          sx={{ p: 1.25, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
          <Box sx={{ width: 26, height: 26, borderRadius: "8px", bgcolor: f.brandSoft, color: f.brand, display: "grid", placeItems: "center", fontWeight: 800, fontSize: 13, flexShrink: 0 }}>
            {index + 1}
          </Box>
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <Typography variant="body2" noWrap sx={{ fontWeight: 600 }}>
              {job.title}
            </Typography>
            <Box sx={{ height: 6, borderRadius: 3, bgcolor: f.line, mt: 0.75, overflow: "hidden" }}>
              <Box sx={{ height: "100%", borderRadius: 3, bgcolor: f.brand, width: `${(job.application_count / maxCount) * 100}%`, minWidth: job.application_count > 0 ? 4 : 0 }} />
            </Box>
          </Box>
          <Typography variant="body2" sx={{ color: f.muted, minWidth: 90, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
            {t("jobs.top.apps", { count: job.application_count })}
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}
