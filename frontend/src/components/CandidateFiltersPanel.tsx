import RestartAltIcon from "@mui/icons-material/RestartAlt";
import { useEffect, useState } from "react";
import Autocomplete from "@mui/material/Autocomplete";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

import BookmarkBorderIcon from "@mui/icons-material/BookmarkBorder";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import Menu from "@mui/material/Menu";
import { experienceApi, http, type SavedViewRow } from "../api/client";
import { APPLICATION_STATUSES, CANDIDATE_SOURCES, candidateSourceLabel, type JobRoleRead } from "../api/types";
import { useT } from "../i18n";
import { statusLabel as applicationStatusLabel } from "./StatusChip";

export interface CandidateFilters {
  jobRoleId: string;
  status: string;
  source: string;
  location: string;
  experienceMin: string;
  experienceMax: string;
  appliedAfter: string;
  appliedBefore: string;
  matchScoreMin: string;
  matchScoreMax: string;
  noticeMax: string; // Part 18.10: "" | days
  tags: string; // Part 18.10: comma-separated
}

export const EMPTY_CANDIDATE_FILTERS: CandidateFilters = {
  jobRoleId: "",
  status: "",
  source: "",
  location: "",
  experienceMin: "",
  experienceMax: "",
  appliedAfter: "",
  appliedBefore: "",
  matchScoreMin: "",
  matchScoreMax: "",
  noticeMax: "",
  tags: "",
};

// Rendered directly above the Candidates List table as a row of separate controls --
// deliberately not a single "Filters" button hiding everything in a popover, since these
// are meant to be visible and adjustable at a glance while scanning the table.
export default function CandidateFiltersPanel({
  jobs,
  filters,
  onChange,
  // Part 17.4: the score range always filters the one Match score (each page passes
  // scoreField "composite_score"), so its label is always "Match score". scoreLabel is
  // accepted for older callers but no longer changes the wording.
  scoreLabel: _scoreLabel,
  // Overrides the Status dropdown's label + option set -- used by the Shortlisting List to
  // show its own 4 named states ("Shortlist Status": Under Review/Shortlisted/On Hold/Not
  // Shortlisted) via `filters.status` instead of the full raw APPLICATION_STATUSES list.
  // Every other caller leaves this unset and gets the original "Status" dropdown.
  statusLabel = "Status",
  statusOptions,
  hide,
  savedKey,
}: {
  jobs: JobRoleRead[];
  filters: CandidateFilters;
  onChange: (filters: CandidateFilters) => void;
  /** @deprecated Ignored -- the label is always "Match score". */
  scoreLabel?: string;
  statusLabel?: string;
  statusOptions?: { value: string; label: string }[];
  /** Part 18.10: filters a page already shows elsewhere (e.g. Shortlisting's own job picker) */
  hide?: (keyof CandidateFilters)[];
  /** Part 18.10: per-user saved filters for pages without a list toolbar */
  savedKey?: string;
}) {
  const t = useT();
  void _scoreLabel;
  const activeCount = Object.values(filters).filter(Boolean).length;
  const set = (key: keyof CandidateFilters, value: string) => onChange({ ...filters, [key]: value });
  const [tagOptions, setTagOptions] = useState<string[]>([]);
  useEffect(() => {
    http.get<{ tag: string }[]>("/api/v1/ui/candidates-tags").then((r) => setTagOptions(r.map((x) => x.tag))).catch(() => setTagOptions([]));
  }, []);

  return (
    <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap alignItems="center">
      {!hide?.includes("jobRoleId") && (
      <TextField
        select
        label="Job"
        size="small"
        value={filters.jobRoleId}
        onChange={(e) => set("jobRoleId", e.target.value)}
        sx={{ minWidth: 160 }}
      >
        <MenuItem value="">All jobs</MenuItem>
        {jobs.map((job) => (
          <MenuItem key={job.id} value={job.id}>
            {job.title}
          </MenuItem>
        ))}
      </TextField>
      )}

      {!hide?.includes("status") && (
      <TextField
        select
        label={statusLabel}
        size="small"
        value={filters.status}
        onChange={(e) => set("status", e.target.value)}
        sx={{ minWidth: 150 }}
      >
        <MenuItem value="">All statuses</MenuItem>
        {/* Part 17.2: a funnel-stage link sets several statuses at once ("a,b,c"). */}
        {filters.status.includes(",") && (
          <MenuItem value={filters.status}>{filters.status.split(",").map(applicationStatusLabel).join(" / ")}</MenuItem>
        )}
        {(statusOptions ?? APPLICATION_STATUSES.map((status) => ({ value: status, label: applicationStatusLabel(status) }))).map(
          (option) => (
            <MenuItem key={option.value} value={option.value}>
              {option.label}
            </MenuItem>
          ),
        )}
      </TextField>
      )}

      <TextField
        select
        label="Source"
        size="small"
        value={filters.source}
        onChange={(e) => set("source", e.target.value)}
        sx={{ minWidth: 140 }}
      >
        <MenuItem value="">All sources</MenuItem>
        {CANDIDATE_SOURCES.map((source) => (
          <MenuItem key={source} value={source}>
            {candidateSourceLabel(source)}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        label="Location"
        size="small"
        value={filters.location}
        onChange={(e) => set("location", e.target.value)}
        placeholder="e.g. Chennai"
        sx={{ minWidth: 130 }}
      />

      <Stack direction="row" spacing={0.5} alignItems="center">
        <TextField
          label="Exp min"
          type="number"
          size="small"
          value={filters.experienceMin}
          onChange={(e) => set("experienceMin", e.target.value)}
          slotProps={{ htmlInput: { min: 0, step: 0.5 } }}
          sx={{ width: 90 }}
        />
        <TextField
          label="Exp max"
          type="number"
          size="small"
          value={filters.experienceMax}
          onChange={(e) => set("experienceMax", e.target.value)}
          slotProps={{ htmlInput: { min: 0, step: 0.5 } }}
          sx={{ width: 90 }}
        />
      </Stack>

      <Stack direction="row" spacing={0.5} alignItems="center">
        <TextField
          label="Applied from"
          type="date"
          size="small"
          value={filters.appliedAfter}
          onChange={(e) => set("appliedAfter", e.target.value)}
          slotProps={{ inputLabel: { shrink: true } }}
          sx={{ width: 160 }}
        />
        <TextField
          label="Applied to"
          type="date"
          size="small"
          value={filters.appliedBefore}
          onChange={(e) => set("appliedBefore", e.target.value)}
          slotProps={{ inputLabel: { shrink: true } }}
          sx={{ width: 160 }}
        />
      </Stack>

      <Stack direction="row" spacing={0.5} alignItems="center">
        <TextField
          label={t("candidates.filter.score_min")}
          type="number"
          size="small"
          value={filters.matchScoreMin}
          onChange={(e) => set("matchScoreMin", e.target.value)}
          slotProps={{ htmlInput: { min: 0, max: 100, step: 5 } }}
          sx={{ width: 150 }}
        />
        <TextField
          label={t("candidates.filter.score_max")}
          type="number"
          size="small"
          value={filters.matchScoreMax}
          onChange={(e) => set("matchScoreMax", e.target.value)}
          slotProps={{ htmlInput: { min: 0, max: 100, step: 5 } }}
          sx={{ width: 150 }}
        />
      </Stack>

      {/* Part 18.10: notice period and tags -- the same on Candidates, Screening and Shortlisting */}
      <TextField select label={t("filters.notice")} size="small" value={filters.noticeMax} onChange={(e) => set("noticeMax", e.target.value)} sx={{ minWidth: 150 }}>
        <MenuItem value="">{t("filters.any")}</MenuItem>
        {["0", "15", "30", "60", "90"].map((d) => <MenuItem key={d} value={d}>{d === "0" ? t("filters.notice_now") : t("filters.notice_upto", { days: d })}</MenuItem>)}
      </TextField>
      <Autocomplete
        multiple size="small" options={tagOptions} value={filters.tags ? filters.tags.split(",") : []}
        onChange={(_e, v) => set("tags", v.join(","))}
        renderInput={(params) => <TextField {...params} label={t("filters.tags")} />}
        sx={{ minWidth: 200 }}
      />

      {savedKey && <SavedFilters listKey={savedKey} filters={filters} onApply={onChange} />}
      <Button
        size="small"
        startIcon={<RestartAltIcon fontSize="small" />}
        onClick={() => onChange(EMPTY_CANDIDATE_FILTERS)}
        disabled={activeCount === 0}
      >
        Reset{activeCount > 0 ? ` (${activeCount})` : ""}
      </Button>
    </Stack>
  );
}

// Part 18.10: saved filters per user (the same /api/v1/views store the list toolbars use)
function SavedFilters({ listKey, filters, onApply }: { listKey: string; filters: CandidateFilters; onApply: (f: CandidateFilters) => void }) {
  const t = useT();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [views, setViews] = useState<SavedViewRow[]>([]);
  const [name, setName] = useState("");
  const load = () => experienceApi.views(listKey).then(setViews).catch(() => setViews([]));
  useEffect(() => { void load(); }, [listKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = async () => {
    if (!name.trim()) return;
    await experienceApi.saveView(listKey, { name: name.trim(), config: { filters } }).catch(() => undefined);
    setName("");
    void load();
  };
  return (
    <>
      <Button size="small" startIcon={<BookmarkBorderIcon fontSize="small" />} onClick={(e) => setAnchor(e.currentTarget)}>{t("filters.saved")}</Button>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
        {views.length === 0 && <MenuItem disabled>{t("filters.saved_none")}</MenuItem>}
        {views.map((v) => (
          <MenuItem key={v.id} onClick={() => { onApply({ ...EMPTY_CANDIDATE_FILTERS, ...((v.config?.filters ?? {}) as Partial<CandidateFilters>) }); setAnchor(null); }}>
            <Box sx={{ flex: 1 }}>{v.name}</Box>
            {v.mine && (
              <IconButton size="small" aria-label={t("filters.saved_delete")}
                onClick={(e) => { e.stopPropagation(); void experienceApi.deleteView(listKey, v.id).then(load); }}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            )}
          </MenuItem>
        ))}
        <Box sx={{ px: 2, py: 1, display: "flex", gap: 1 }} onKeyDown={(e) => e.stopPropagation()}>
          <TextField size="small" placeholder={t("filters.saved_name")} value={name} onChange={(e) => setName(e.target.value)} />
          <Button size="small" variant="contained" disabled={!name.trim()} onClick={save}>{t("filters.saved_save")}</Button>
        </Box>
      </Menu>
    </>
  );
}
