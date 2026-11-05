import { useEffect, useMemo, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import MenuItem from "@mui/material/MenuItem";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import SearchIcon from "@mui/icons-material/Search";
import MailOutlineIcon from "@mui/icons-material/MailOutline";

import { peopleApi, skillList, type PeopleFilters, type PersonRow } from "../../api/peopleApi";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import RefreshButton from "../../components/RefreshButton";
import { EmployeeStatusChip } from "../../components/people/shared";
import { useT } from "../../i18n";
import { EmptyState, Emoji, FriendlyError, PageHeader, UserAvatar } from "../../ui-kit";

// E3 People directory: find a colleague by name, role, department, office or skill. Honours
// ?location=<officeId> (the home page's office map links here), ?department=, ?skill= and ?q=.

const STEP = 48;
const CURRENT = ["active", "on_notice", "pre_hire"];

export default function DirectoryPage({ embedded = false }: { embedded?: boolean }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { can, loading: bootLoading } = useMeBootstrap();
  const canView = can("core_hr.employee.view");
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const department = params.get("department") ?? "";
  const location = params.get("location") ?? "";
  const skill = params.get("skill") ?? "";

  const [rows, setRows] = useState<PersonRow[] | null>(null);
  const [filters, setFilters] = useState<PeopleFilters | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [limit, setLimit] = useState(STEP);

  const patch = (next: Record<string, string>) => {
    const p = new URLSearchParams(params);
    Object.entries(next).forEach(([k, v]) => (v ? p.set(k, v) : p.delete(k)));
    setParams(p, { replace: true });
    setLimit(STEP);
  };

  const load = () => {
    setLoading(true);
    setError(null);
    // Part 17.9: everyone may use the directory; people without HR access get the directory fields only.
    const view = canView ? "hr" : "directory";
    return Promise.all([peopleApi.list({ status: CURRENT.join(","), view }), peopleApi.filters(view)])
      .then(([list, flt]) => {
        setRows(list.items);
        setFilters(flt);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    if (!bootLoading) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canView, bootLoading]);

  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (rows ?? []).filter((r) => {
      if (department && r.department_id !== department) return false;
      if (location && r.location_id !== location) return false;
      const skills = skillList(r.skills);
      if (skill && !skills.some((s) => s.toLowerCase() === skill.toLowerCase())) return false;
      if (!needle) return true;
      return [r.name, r.designation, r.department, r.location, r.work_email, skills.join(" ")].filter(Boolean).join(" ").toLowerCase().includes(needle);
    });
  }, [rows, q, department, location, skill]);

  const locationName = filters?.locations.find((l) => l.id === location)?.name;
  const skillOptions = (filters?.skills ?? []).map((s) => s.name);
  const hasFilters = Boolean(q || department || location || skill);

  return (
    <Box>
      {!embedded && (
        <PageHeader
          emoji="people"
          title={t("people.directory.title")}
          purpose={t("people.directory.purpose")}
          tourKey="directory"
          primary={<Button variant="contained" component={RouterLink} to="/org-chart" startIcon={<Emoji name="building" size={18} />}>{t("people.directory.org_chart")}</Button>}
        />
      )}

      <Card sx={{ p: { xs: 1.5, sm: 2 }, mb: 2.5 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }} useFlexGap flexWrap="wrap">
          <TextField size="small" placeholder={t("people.directory.search_placeholder")} value={q} onChange={(e) => patch({ q: e.target.value })}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }, htmlInput: { "aria-label": t("people.search_label") } }}
            sx={{ flex: 1, minWidth: 260 }} />
          <TextField select size="small" label={t("people.field.department")} value={filters ? department : ""} onChange={(e) => patch({ department: e.target.value })} sx={{ minWidth: 190 }}>
            <MenuItem value="">{t("people.filter.all_departments")}</MenuItem>
            {(filters?.departments ?? []).filter((d) => d.count > 0 || d.id === department).map((d) => <MenuItem key={d.id} value={d.id}>{t("people.filter.option", { name: d.name, count: d.count })}</MenuItem>)}
          </TextField>
          <TextField select size="small" label={t("people.field.location")} value={filters ? location : ""} onChange={(e) => patch({ location: e.target.value })} sx={{ minWidth: 190 }}>
            <MenuItem value="">{t("people.filter.all_locations")}</MenuItem>
            {(filters?.locations ?? []).filter((l) => l.count > 0 || l.id === location).map((l) => <MenuItem key={l.id} value={l.id}>{t("people.filter.option", { name: l.name, count: l.count })}</MenuItem>)}
          </TextField>
          {skillOptions.length > 0 && (
            <Autocomplete size="small" options={skillOptions} value={skill || null} onChange={(_e, v) => patch({ skill: v ?? "" })} sx={{ minWidth: 220 }}
              renderInput={(p) => <TextField {...p} label={t("people.directory.skill")} placeholder={t("people.directory.skill_placeholder")} />} />
          )}
          <RefreshButton loading={loading} onRefresh={load} />
        </Stack>
        {rows && (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1.5, flexWrap: "wrap", rowGap: 1 }}>
            <Typography sx={{ color: f.muted, fontSize: 14 }} aria-live="polite">
              {locationName ? t("people.directory.count_in", { count: visible.length, place: locationName }) : t("people.directory.count", { count: visible.length })}
            </Typography>
            {hasFilters && <Button size="small" onClick={() => patch({ q: "", department: "", location: "", skill: "" })}>{t("people.clear_filters")}</Button>}
          </Stack>
        )}
      </Card>

      {error != null ? (
        <FriendlyError error={error} what={t("people.directory.load_failed")} onRetry={load} />
      ) : rows === null ? (
        <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
          {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} variant="rounded" height={190} />)}
        </Box>
      ) : visible.length === 0 ? (
        <Card>
          {rows.length === 0 ? (
            <EmptyState illustration="meet-the-team" title={t("people.directory.empty")}
              action={can("core_hr.employee.create") ? <Button variant="contained" component={RouterLink} to="/employees">{t("people.directory.empty_action")}</Button> : undefined} />
          ) : (
            <EmptyState compact illustration="people-search" title={t("people.directory.empty_filtered")}
              action={<Button variant="outlined" onClick={() => patch({ q: "", department: "", location: "", skill: "" })}>{t("people.clear_filters")}</Button>} />
          )}
        </Card>
      ) : (
        <>
          <Box component="ul" aria-label={t("people.directory.list")} sx={{ listStyle: "none", m: 0, p: 0, display: "grid", gap: 2, gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
            {visible.slice(0, limit).map((r) => <PersonCard key={r.id} person={r} canOpen={canView} onSkill={(s) => patch({ skill: s })} />)}
          </Box>
          {visible.length > limit && (
            <Stack alignItems="center" sx={{ mt: 2.5 }}>
              <Button variant="outlined" onClick={() => setLimit((l) => l + STEP)}>{t("people.directory.more", { count: visible.length - limit })}</Button>
            </Stack>
          )}
        </>
      )}
    </Box>
  );
}

function PersonCard({ person, canOpen, onSkill }: { person: PersonRow; canOpen: boolean; onSkill: (s: string) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const skills = skillList(person.skills);
  const email = person.work_email || person.personal_email;
  return (
    <Box component="li" sx={{ minWidth: 0 }}>
      <Card sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
        <CardActionArea {...(canOpen ? { component: RouterLink, to: `/employees/${person.id}` } : { disabled: true, disableRipple: true })} sx={{ p: 2, flex: 1, display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 1.25 }}
          aria-label={t("people.directory.open", { name: person.name })}>
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ width: "100%", minWidth: 0 }}>
            <UserAvatar name={person.name} src={person.photo_url} size={56} />
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Typography sx={{ fontWeight: 800, fontSize: 16, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{person.name}</Typography>
              <Typography sx={{ color: f.muted, fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{person.designation || t("people.profile.no_designation")}</Typography>
            </Box>
          </Stack>
          <Stack spacing={0.5}>
            {person.department && <Typography sx={{ fontSize: 13, color: f.muted, display: "flex", gap: 0.75, alignItems: "center" }}><Emoji name="building" size={14} />{person.department}</Typography>}
            {person.location && <Typography sx={{ fontSize: 13, color: f.muted, display: "flex", gap: 0.75, alignItems: "center" }}><Emoji name="pin" size={14} />{person.location}</Typography>}
          </Stack>
          {person.status !== "active" && <EmployeeStatusChip status={person.status} />}
        </CardActionArea>
        <Stack direction="row" spacing={0.75} alignItems="center" sx={{ px: 2, pb: 1.5, pt: 0.5, flexWrap: "wrap", rowGap: 0.75 }}>
          {skills.slice(0, 3).map((s) => <Chip key={s} size="small" label={s} onClick={() => onSkill(s)} aria-label={t("people.directory.filter_skill", { skill: s })} />)}
          {skills.length > 3 && <Typography sx={{ fontSize: 12, color: f.muted }}>{t("people.directory.more_skills", { count: skills.length - 3 })}</Typography>}
          {email && (
            <Tooltip title={t("people.directory.email", { name: person.name })}>
              <IconButton size="small" href={`mailto:${email}`} aria-label={t("people.directory.email", { name: person.name })} sx={{ ml: "auto" }}>
                <MailOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
        </Stack>
      </Card>
    </Box>
  );
}
