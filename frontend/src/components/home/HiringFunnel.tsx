// Part 17.2: "Where candidates go" as a horizontal funnel -- one bar per stage (names from the
// company's own pipeline), the count, % of the stage before, and between bars how many did
// not move on ("-88 did not move on: 60 not selected, 28 still waiting"). Period + job filters.
// Clicking a bar opens the candidate list filtered to everyone who reached that stage.
import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import CircularProgress from "@mui/material/CircularProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useNavigate } from "react-router-dom";

import { jobsApi } from "../../api/client";
import { homeApi, type FunnelPeriod, type HiringFunnelData } from "../../api/homeApi";
import type { JobRoleRead } from "../../api/types";
import { useI18n, useT } from "../../i18n";
import { EmptyState, FriendlyError } from "../../ui-kit";

const PERIODS: FunnelPeriod[] = ["7d", "30d", "90d", "year"];

export function useFunnel(period: FunnelPeriod, jobId: string) {
  const { locale } = useI18n();
  const [data, setData] = useState<HiringFunnelData | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    homeApi.funnel(period, jobId || undefined, locale).then((d) => live && setData(d)).catch((e) => live && setError(e));
    return () => { live = false; };
  }, [period, jobId, locale, tick]);
  return { data, error, reload: () => setTick((x) => x + 1) };
}

export function FunnelFilters({ period, onPeriod, jobId, onJob }: { period: FunnelPeriod; onPeriod: (p: FunnelPeriod) => void; jobId: string; onJob: (id: string) => void }) {
  const t = useT();
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  useEffect(() => { jobsApi.list().then(setJobs).catch(() => setJobs([])); }, []);
  return (
    <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ mb: 1.5 }}>
      <ToggleButtonGroup size="small" exclusive value={period} onChange={(_e, v) => v && onPeriod(v)} aria-label={t("home.funnel.period")}>
        {PERIODS.map((p) => <ToggleButton key={p} value={p} sx={{ px: 1.25, textTransform: "none" }}>{t(`home.funnel.period.${p}`)}</ToggleButton>)}
      </ToggleButtonGroup>
      <TextField select size="small" label={t("home.funnel.job")} value={jobId} onChange={(e) => onJob(e.target.value)} sx={{ minWidth: 200 }}>
        <MenuItem value="">{t("home.funnel.all_jobs")}</MenuItem>
        {jobs.map((j) => <MenuItem key={j.id} value={j.id}>{j.title}</MenuItem>)}
      </TextField>
    </Stack>
  );
}

export function FunnelBars({ data }: { data: HiringFunnelData }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const navigate = useNavigate();
  const max = Math.max(1, ...data.stages.map((s) => s.count));
  const name = (i: number) => data.stages[i].label || t(`home.funnel.stage.${data.stages[i].key}`);

  const open = (i: number) => {
    const qs = new URLSearchParams({ status: data.stages[i].statuses.join(","), applied_after: data.since });
    if (data.job_id) qs.set("job", data.job_id);
    navigate(`/candidates/list?${qs.toString()}`);
  };

  return (
    <Stack component="ol" spacing={0} sx={{ listStyle: "none", p: 0, m: 0 }} aria-label={t("home.w.flow")}>
      {data.stages.map((s, i) => {
        const width = Math.max(s.count ? 4 : 0, Math.round((100 * s.count) / max));
        const last = i === data.stages.length - 1;
        return (
          <Box component="li" key={s.key}>
            <ButtonBase onClick={() => open(i)} aria-label={t("home.funnel.open", { stage: name(i), count: s.count })}
              sx={{ display: "grid", gridTemplateColumns: { xs: "96px 1fr", sm: "130px 1fr 92px" }, alignItems: "center", gap: 1.25,
                width: "100%", textAlign: "left", borderRadius: "10px", px: 0.75, py: 0.5, "&:hover, &:focus-visible": { bgcolor: f.brandSoft } }}>
              <Typography sx={{ fontWeight: 700, fontSize: 14 }} noWrap>{name(i)}</Typography>
              <Box sx={{ position: "relative", height: 28, bgcolor: f.surface2, borderRadius: "8px", overflow: "hidden" }}>
                <Box sx={{ position: "absolute", inset: 0, width: `${width}%`, bgcolor: i === data.stages.length - 1 ? f.ok ?? f.brand : f.brand,
                  opacity: 1 - i * 0.09, borderRadius: "8px", transition: "width .4s" }} />
                <Typography sx={{ position: "relative", px: 1, lineHeight: "28px", fontWeight: 800, fontSize: 14,
                  color: width > 18 ? f.brandInk : f.ink }}>{s.count.toLocaleString()}</Typography>
              </Box>
              <Typography sx={{ fontSize: 13, color: f.muted, display: { xs: "none", sm: "block" }, textAlign: "right" }}>
                {s.pct_of_previous === null ? t("home.funnel.start") : t("home.funnel.pct", { pct: s.pct_of_previous })}
              </Typography>
            </ButtonBase>
            {!last && s.drop > 0 && (
              <Typography sx={{ fontSize: 12.5, color: f.muted, pl: { xs: "108px", sm: "142px" }, py: 0.25 }}>
                <Box component="span" sx={{ color: f.coral, fontWeight: 700 }}>−{s.drop.toLocaleString()}</Box>{" "}
                {t("home.funnel.drop", { next: name(i + 1) })}
                {s.stopped > 0 || s.still_here > 0 ? ` · ${t("home.funnel.drop_split", { stopped: s.stopped, waiting: s.still_here })}` : ""}
              </Typography>
            )}
          </Box>
        );
      })}
    </Stack>
  );
}

export default function HiringFunnel() {
  const t = useT();
  const [period, setPeriod] = useState<FunnelPeriod>("30d");
  const [jobId, setJobId] = useState("");
  const { data, error, reload } = useFunnel(period, jobId);
  return (
    <Box>
      <FunnelFilters period={period} onPeriod={setPeriod} jobId={jobId} onJob={setJobId} />
      {error ? <FriendlyError error={error} onRetry={reload} compact /> : data === null ? (
        <Box sx={{ display: "grid", placeItems: "center", py: 3 }}><CircularProgress aria-label={t("home.loading")} /></Box>
      ) : data.total === 0 ? (
        <EmptyState compact illustration="hiring" title={t("home.funnel.empty")} hint={t("home.funnel.empty_hint")} />
      ) : (
        <FunnelBars data={data} />
      )}
    </Box>
  );
}
