import { lazy, Suspense, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell as BarCell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { homeApi } from "../../api/homeApi";
import { insightsApi, type JobLocation } from "../../api/insightsApi";
import { CardLoading, InsightCard, useLoaded, type Loaded } from "../../components/insights/InsightCard";
import { useT } from "../../i18n";
import { Cell, EmptyState, Emoji, FriendlyError, PageGrid, PageHeader, StatTile } from "../../ui-kit";
import { useReducedMotion } from "../../ui-kit/motion";

// Part 15.6 L-V1/V2/V3/V5: Analytics dashboards -- where candidates go (Sankey), open jobs by
// location, where candidates live (city heat-map, never an address, at least 5 per spot),
// people by office (clusters). Every place clicks through to the matching list.

const HiringSankey = lazy(() => import("../../components/home/HiringSankey"));
const HiringFunnel = lazy(() => import("../../components/home/HiringFunnel"));
const PlacesMap = lazy(() => import("../../components/maps/PlacesMap"));
const CandidateHeatMap = lazy(() => import("../../components/insights/InsightsMaps").then((m) => ({ default: m.CandidateHeatMap })));

function Body<T>({ value, reload, empty, children }: { value: Loaded<T>; reload: () => void; empty: (d: T) => boolean; children: (d: T) => React.ReactNode }) {
  const t = useT();
  if (value.state === "loading") return <CardLoading />;
  if (value.state === "error") return <FriendlyError error={value.error} onRetry={reload} compact />;
  if (value.state === "forbidden") return <Typography sx={{ color: "text.secondary", py: 2 }}>{t("analytics.no_access")}</Typography>;
  if (empty(value.data)) return <EmptyState compact illustration="no-data" title={t("analytics.empty")} />;
  return <Suspense fallback={<CardLoading />}>{children(value.data)}</Suspense>;
}

function JobsBar({ locations }: { locations: JobLocation[] }) {
  const t = useT();
  const theme = useTheme();
  const f = theme.palette.fresh;
  const reduced = useReducedMotion();
  const navigate = useNavigate();
  const data = locations.slice(0, 8).map((l) => ({ name: l.location || t("analytics.maps.no_location"), value: l.count, raw: l.location }));
  const summary = data.map((d) => `${d.name}: ${t("analytics.maps.jobs", { count: d.value })}`).join(", ");
  return (
    <Box role="img" aria-label={summary} sx={{ width: "100%", height: Math.max(160, data.length * 36) }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid horizontal={false} stroke={f.line} />
          <XAxis type="number" allowDecimals={false} tick={{ fill: f.muted, fontSize: 12 }} stroke={f.line} />
          <YAxis type="category" dataKey="name" width={110} tick={{ fill: f.ink, fontSize: 12 }} stroke={f.line} />
          <Tooltip formatter={(v) => t("analytics.maps.jobs", { count: Number(v) })} contentStyle={{ borderRadius: 12, border: `1px solid ${f.line}`, background: f.surface, color: f.ink }} />
          <Bar dataKey="value" radius={[0, 6, 6, 0]} isAnimationActive={!reduced} cursor="pointer"
            onClick={(bar) => { const d = (bar as unknown as { payload?: { raw?: string | null } }).payload ?? {}; navigate(`/jobs?status=published${d.raw ? `&location=${encodeURIComponent(d.raw)}` : ""}`); }}>
            {data.map((d, i) => <BarCell key={d.name} fill={theme.palette.chart[i % theme.palette.chart.length]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </Box>
  );
}

export default function AnalyticsPage() {
  const t = useT();
  const [flow, reloadFlow] = useLoaded(homeApi.hiringFlow);
  // Part 17.2: the funnel is the default; the Sankey is kept as the optional "Flow view".
  const [flowView, setFlowView] = useState(false);
  const [jobs, reloadJobs] = useLoaded(insightsApi.jobsByLocation);
  const [heat, reloadHeat] = useLoaded(insightsApi.candidateHeat);
  const [offices, reloadOffices] = useLoaded(homeApi.offices);

  const num = <T,>(v: Loaded<T>, pick: (d: T) => number) => (v.state === "ok" ? pick(v.data) : "—");

  return (
    <Box>
      <PageHeader
        emoji="chart_up"
        title={t("analytics.title")}
        purpose={t("analytics.purpose")}
        tourKey="analytics"
        primary={
          <Button variant="contained" component={RouterLink} to="/reports/builder" startIcon={<Emoji name="bar_chart" size={16} />}>
            {t("analytics.build_report")}
          </Button>
        }
      />

      <PageGrid>
        <Cell span={{ xs: 12, sm: 6, lg: 3 }}>
          <StatTile emoji="technologist" value={num(flow, (d) => d.total)} label={t("analytics.tile.applications")} loading={flow.state === "loading"} to="/candidates/list" />
        </Cell>
        <Cell span={{ xs: 12, sm: 6, lg: 3 }}>
          <StatTile emoji="briefcase" tone="sky" value={num(jobs, (d) => d.total)} label={t("analytics.tile.open_jobs")} loading={jobs.state === "loading"} to="/jobs?status=published" />
        </Cell>
        <Cell span={{ xs: 12, sm: 6, lg: 3 }}>
          <StatTile emoji="pin" tone="sun" value={num(heat, (d) => d.cells.length)} label={t("analytics.tile.candidate_cities")} loading={heat.state === "loading"} />
        </Cell>
        <Cell span={{ xs: 12, sm: 6, lg: 3 }}>
          <StatTile emoji="people" tone="ok" value={num(offices, (d) => d.offices.reduce((a, o) => a + o.count, 0))} label={t("analytics.tile.people")} loading={offices.state === "loading"} to="/directory" />
        </Cell>

        <Cell span={{ xs: 12, lg: 7 }}>
          <InsightCard emoji="compass" title={t("analytics.flow.title")} sub={t("analytics.flow.sub")} dataTour="analytics-flow">
            <Stack direction="row" justifyContent="flex-end" sx={{ mb: 1 }}>
              <ToggleButtonGroup size="small" exclusive value={flowView ? "flow" : "funnel"} onChange={(_e, v) => v && setFlowView(v === "flow")}>
                <ToggleButton value="funnel" sx={{ textTransform: "none" }}>{t("home.funnel.funnel_view")}</ToggleButton>
                <ToggleButton value="flow" sx={{ textTransform: "none" }}>{t("home.funnel.flow_view")}</ToggleButton>
              </ToggleButtonGroup>
            </Stack>
            {flowView ? (
              <Body value={flow} reload={reloadFlow} empty={(d) => d.total === 0}>{(d) => <HiringSankey flow={d} height={300} />}</Body>
            ) : (
              <Suspense fallback={null}><HiringFunnel /></Suspense>
            )}
          </InsightCard>
        </Cell>
        <Cell span={{ xs: 12, lg: 5 }}>
          <InsightCard emoji="bar_chart" title={t("analytics.jobs_bar.title")} sub={t("analytics.jobs_bar.sub")}>
            <Body value={jobs} reload={reloadJobs} empty={(d) => d.locations.length === 0}>{(d) => <JobsBar locations={d.locations} />}</Body>
          </InsightCard>
        </Cell>

        <Cell span={{ xs: 12, lg: 6 }}>
          <InsightCard emoji="briefcase" title={t("analytics.jobs_map.title")} sub={t("analytics.jobs_map.sub")}>
            <Body value={jobs} reload={reloadJobs} empty={(d) => d.locations.length === 0}>{() => <PlacesMap kind="jobs" />}</Body>
          </InsightCard>
        </Cell>
        <Cell span={{ xs: 12, lg: 6 }}>
          <InsightCard emoji="fire" title={t("analytics.heat.title")} sub={t("analytics.heat.sub")} help={t("analytics.heat.help", { min: 5 })} dataTour="analytics-heat">
            <Body value={heat} reload={reloadHeat} empty={(d) => d.cells.length === 0 && d.hidden_small === 0}>
              {(d) => (
                <>
                  {d.cells.length > 0 ? <CandidateHeatMap cells={d.cells} /> : <EmptyState compact illustration="location-search" title={t("analytics.heat.too_few", { min: d.min_cell })} />}
                  {(d.hidden_small > 0 || d.unknown > 0) && (
                    <Typography variant="caption" component="p" sx={{ mt: 1, color: "text.secondary" }}>
                      {[d.hidden_small > 0 ? t("analytics.heat.hidden", { count: d.hidden_small, min: d.min_cell }) : "", d.unknown > 0 ? t("analytics.heat.unknown", { count: d.unknown }) : ""].filter(Boolean).join(" ")}
                    </Typography>
                  )}
                </>
              )}
            </Body>
          </InsightCard>
        </Cell>

        <Cell span={12}>
          <InsightCard emoji="building" title={t("analytics.offices.title")} sub={t("analytics.offices.sub")}>
            <Body value={offices} reload={reloadOffices} empty={(d) => d.offices.length === 0}>{() => <PlacesMap kind="offices" height={360} />}</Body>
          </InsightCard>
        </Cell>
      </PageGrid>
    </Box>
  );
}
