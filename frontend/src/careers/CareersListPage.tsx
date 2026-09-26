import { useEffect, useMemo, useState } from "react";
import SearchIcon from "@mui/icons-material/Search";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import InputAdornment from "@mui/material/InputAdornment";
import MenuItem from "@mui/material/MenuItem";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useNavigate } from "react-router-dom";

import { publicApi } from "../api/client";
import type { PublicJobRead } from "../api/types";
import { useBootstrap } from "../bootstrap/BootstrapContext";
import { BenefitsSection, FaqSection, useCareersSite } from "../components/careers/CareersSections";
import JobFacts from "../components/careers/JobFacts";
import { useT } from "../i18n";
import { EmptyState, FriendlyError, Illustration } from "../ui-kit";
import { categorizeSkills } from "../utils/skills";

const uniq = (values: (string | null | undefined)[]) => Array.from(new Set(values.filter((v): v is string => Boolean(v && v.trim())))).sort((a, b) => a.localeCompare(b));

export default function CareersListPage() {
  const f = useTheme().palette.fresh;
  const t = useT();
  const navigate = useNavigate();
  const { productName } = useBootstrap();
  const site = useCareersSite();
  const [jobs, setJobs] = useState<PublicJobRead[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [query, setQuery] = useState("");
  const [department, setDepartment] = useState("");
  const [location, setLocation] = useState("");

  const load = () => {
    setError(null);
    publicApi
      .listJobs()
      .then(setJobs)
      .catch((err) => setError(err));
  };

  useEffect(load, []);

  const departments = useMemo(() => uniq((jobs ?? []).map((j) => j.department)), [jobs]);
  const locations = useMemo(() => uniq((jobs ?? []).map((j) => j.location)), [jobs]);

  const filtered = useMemo(() => {
    const q = query.trim().toLocaleLowerCase();
    return (jobs ?? []).filter((job) => {
      if (department && job.department !== department) return false;
      if (location && job.location !== location) return false;
      if (!q) return true;
      const { mustHave, goodToHave } = categorizeSkills(job);
      return [job.title, job.department, job.location, ...mustHave, ...goodToHave].some((v) => v?.toLocaleLowerCase().includes(q));
    });
  }, [jobs, query, department, location]);

  const filtering = Boolean(query.trim() || department || location);
  const clear = () => {
    setQuery("");
    setDepartment("");
    setLocation("");
  };

  return (
    <Stack spacing={5}>
      <Card component="section" sx={{ p: { xs: 3, md: 4 }, background: `linear-gradient(120deg, ${f.brandSoft}, ${f.surface} 70%)` }}>
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr auto" }, gap: 3, alignItems: "center" }}>
          <Box>
            <Typography variant="h1" component="h1" sx={{ fontSize: { xs: 28, md: 34 } }}>{t("careers.hero_title", { name: productName })}</Typography>
            <Typography sx={{ color: f.muted, mt: 1, maxWidth: "60ch", whiteSpace: "pre-wrap" }}>{site?.intro || t("careers.hero_sub")}</Typography>
            {jobs && jobs.length > 0 && (
              <Typography sx={{ fontWeight: 700, mt: 2, color: f.brand }}>{t("count.open_jobs", { count: jobs.length })}</Typography>
            )}
          </Box>
          <Box sx={{ display: { xs: "none", md: "block" } }}>
            <Illustration name="hiring" height={170} />
          </Box>
        </Box>
      </Card>

      <Box component="section" aria-labelledby="careers-jobs-title">
        <Typography id="careers-jobs-title" component="h2" sx={{ fontWeight: 800, fontSize: 22, mb: 2 }}>{t("careers.open_positions")}</Typography>

        <Box role="search" sx={{ display: "flex", flexWrap: "wrap", gap: 1.5, mb: 2.5 }}>
          <TextField
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("careers.search_placeholder")}
            size="small"
            sx={{ flex: "1 1 260px" }}
            slotProps={{
              htmlInput: { "aria-label": t("careers.search_label") },
              input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> },
            }}
          />
          {departments.length > 1 && (
            <TextField select size="small" label={t("careers.filter_department")} value={department} onChange={(e) => setDepartment(e.target.value)} sx={{ minWidth: 180 }}>
              <MenuItem value="">{t("careers.filter_all")}</MenuItem>
              {departments.map((d) => <MenuItem key={d} value={d}>{d}</MenuItem>)}
            </TextField>
          )}
          {locations.length > 1 && (
            <TextField select size="small" label={t("careers.filter_location")} value={location} onChange={(e) => setLocation(e.target.value)} sx={{ minWidth: 180 }}>
              <MenuItem value="">{t("careers.filter_all")}</MenuItem>
              {locations.map((l) => <MenuItem key={l} value={l}>{l}</MenuItem>)}
            </TextField>
          )}
          {filtering && <Button onClick={clear}>{t("careers.filter_clear")}</Button>}
        </Box>

        {error !== null ? (
          <FriendlyError error={error} what={t("careers.load_failed")} fix={t("careers.load_failed_fix")} onRetry={load} />
        ) : jobs === null ? (
          <Stack spacing={1.5} aria-busy="true">
            {[0, 1, 2].map((i) => <Skeleton key={i} variant="rounded" height={104} />)}
          </Stack>
        ) : jobs.length === 0 ? (
          <Card><EmptyState illustration="empty" title={t("careers.none_title")} hint={t("careers.none_hint")} /></Card>
        ) : filtered.length === 0 ? (
          <Card>
            <EmptyState illustration="search" title={t("careers.no_match")} action={<Button variant="contained" onClick={clear}>{t("careers.filter_clear")}</Button>} />
          </Card>
        ) : (
          <Stack spacing={1.5}>
            {filtering && (
              <Typography sx={{ color: f.muted }} role="status">{t("careers.showing", { count: filtered.length, total: jobs.length })}</Typography>
            )}
            {filtered.map((job) => {
              const { mustHave } = categorizeSkills(job);
              return (
                <Card key={job.id}>
                  <CardActionArea onClick={() => navigate(`/careers/${job.id}`)} sx={{ p: 2.5 }}>
                    <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ xs: "flex-start", sm: "center" }} justifyContent="space-between">
                      <Box sx={{ minWidth: 0 }}>
                        <Typography component="h3" sx={{ fontWeight: 700, fontSize: 18, mb: 1 }}>{job.title}</Typography>
                        <JobFacts job={job} />
                        {mustHave.length > 0 && (
                          <Typography variant="body2" sx={{ color: f.muted, mt: 1.25 }}>
                            {t("careers.skills_line", { skills: mustHave.slice(0, 6).join(", ") })}
                          </Typography>
                        )}
                      </Box>
                      <Box component="span" sx={{ flexShrink: 0, fontWeight: 700, color: f.brand, whiteSpace: "nowrap" }}>{t("careers.view_job")} →</Box>
                    </Stack>
                  </CardActionArea>
                </Card>
              );
            })}
          </Stack>
        )}
      </Box>

      <BenefitsSection site={site} />
      <FaqSection site={site} />
    </Stack>
  );
}
