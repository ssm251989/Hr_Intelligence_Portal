// Part 17.12: one person's interview availability -- a weekly hours grid (each day off, or
// one or more time ranges in company time), blocked dates, and daily / weekly limits.
// Used on "My availability" and by HR editing someone's availability.
import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { DAY_KEYS, type AvailabilityIn, type BlockedDate, type DayKey, type TimeRange, type WeeklyPattern } from "../../api/interviewersApi";
import { useT } from "../../i18n";
import { Emoji, FriendlyError } from "../../ui-kit";

const DEFAULT_RANGE: TimeRange = { start: "10:00", end: "18:00" };

export default function AvailabilityEditor({ initial, onSave, saving, error }: {
  initial: { weekly_pattern: WeeklyPattern; exceptions: BlockedDate[]; max_interviews_per_day: number | null; max_interviews_per_week: number | null };
  onSave: (payload: AvailabilityIn) => void;
  saving: boolean;
  error?: unknown;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [week, setWeek] = useState<WeeklyPattern>({});
  const [blocked, setBlocked] = useState<BlockedDate[]>([]);
  const [perDay, setPerDay] = useState("");
  const [perWeek, setPerWeek] = useState("");
  const [newDate, setNewDate] = useState("");
  const [newNote, setNewNote] = useState("");

  useEffect(() => {
    const w: WeeklyPattern = {};
    for (const d of DAY_KEYS) {
      const v = initial.weekly_pattern[d];
      w[d] = v === false ? false : Array.isArray(v) && v.length ? v.map((r) => ({ start: r.start, end: r.end })) : [{ ...DEFAULT_RANGE }];
    }
    setWeek(w);
    setBlocked(initial.exceptions.filter((e) => e.available === false || e.available === undefined));
    setPerDay(initial.max_interviews_per_day ? String(initial.max_interviews_per_day) : "");
    setPerWeek(initial.max_interviews_per_week ? String(initial.max_interviews_per_week) : "");
  }, [initial]);

  const setDay = (d: DayKey, v: TimeRange[] | false) => setWeek((w) => ({ ...w, [d]: v }));
  const ranges = (d: DayKey) => (Array.isArray(week[d]) ? (week[d] as TimeRange[]) : []);
  const invalid = DAY_KEYS.some((d) => ranges(d).some((r) => !r.start || !r.end || r.start >= r.end));

  return (
    <Stack spacing={2.5}>
      <Box>
        <Typography component="h3" sx={{ fontWeight: 800, mb: 0.5 }}>{t("interviewers.week.title")}</Typography>
        <Typography sx={{ fontSize: 13, color: f.muted, mb: 1 }}>{t("interviewers.week.hint")}</Typography>
        <Stack spacing={0.75}>
          {DAY_KEYS.map((d) => {
            const on = week[d] !== false;
            return (
              <Stack key={d} direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}
                sx={{ border: `1px solid ${f.line}`, borderRadius: "10px", px: 1.25, py: 0.75, bgcolor: on ? f.surface : f.surface2 }}>
                <Stack direction="row" alignItems="center" sx={{ minWidth: 170 }}>
                  <Switch checked={on} onChange={(e) => setDay(d, e.target.checked ? [{ ...DEFAULT_RANGE }] : false)} inputProps={{ "aria-label": t(`interviewers.day.${d}`) }} />
                  <Typography sx={{ fontWeight: 700 }}>{t(`interviewers.day.${d}`)}</Typography>
                </Stack>
                {!on ? <Typography sx={{ fontSize: 14, color: f.muted }}>{t("interviewers.week.off")}</Typography> : (
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
                    {ranges(d).map((r, i) => (
                      <Stack key={i} direction="row" spacing={0.5} alignItems="center">
                        <TextField type="time" size="small" value={r.start} inputProps={{ "aria-label": t("interviewers.week.from") }}
                          onChange={(e) => setDay(d, ranges(d).map((x, j) => (j === i ? { ...x, start: e.target.value } : x)))} error={r.start >= r.end} />
                        <Typography>–</Typography>
                        <TextField type="time" size="small" value={r.end} inputProps={{ "aria-label": t("interviewers.week.to") }}
                          onChange={(e) => setDay(d, ranges(d).map((x, j) => (j === i ? { ...x, end: e.target.value } : x)))} error={r.start >= r.end} />
                        {ranges(d).length > 1 && (
                          <IconButton size="small" aria-label={t("interviewers.week.remove_range")} onClick={() => setDay(d, ranges(d).filter((_x, j) => j !== i))}>
                            <Emoji name="cross" size={12} />
                          </IconButton>
                        )}
                      </Stack>
                    ))}
                    <Button size="small" onClick={() => setDay(d, [...ranges(d), { start: "14:00", end: "17:00" }])}>{t("interviewers.week.add_range")}</Button>
                  </Stack>
                )}
              </Stack>
            );
          })}
        </Stack>
        {invalid && <Typography role="alert" sx={{ fontSize: 13, color: f.coral, mt: 0.5 }}>{t("interviewers.week.invalid")}</Typography>}
      </Box>

      <Box>
        <Typography component="h3" sx={{ fontWeight: 800, mb: 0.5 }}>{t("interviewers.blocked.title")}</Typography>
        <Typography sx={{ fontSize: 13, color: f.muted, mb: 1 }}>{t("interviewers.blocked.hint")}</Typography>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 1 }}>
          <TextField type="date" size="small" label={t("interviewers.blocked.date")} value={newDate} onChange={(e) => setNewDate(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField size="small" label={t("interviewers.blocked.note")} value={newNote} onChange={(e) => setNewNote(e.target.value)} sx={{ flex: 1 }} />
          <Button variant="outlined" disabled={!newDate || blocked.some((b) => b.date === newDate)}
            onClick={() => { setBlocked((b) => [...b, { date: newDate, available: false, note: newNote || undefined }].sort((a, b2) => a.date.localeCompare(b2.date))); setNewDate(""); setNewNote(""); }}>
            {t("interviewers.blocked.add")}
          </Button>
        </Stack>
        {blocked.length === 0 ? <Typography sx={{ fontSize: 14, color: f.muted }}>{t("interviewers.blocked.none")}</Typography> : (
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {blocked.map((b) => (
              <Stack key={b.date} direction="row" spacing={0.5} alignItems="center" sx={{ border: `1px solid ${f.line}`, borderRadius: 999, pl: 1.5, pr: 0.5, py: 0.25 }}>
                <Typography sx={{ fontSize: 13 }}>{b.date}{b.note ? ` · ${b.note}` : ""}</Typography>
                <IconButton size="small" aria-label={t("interviewers.blocked.remove", { date: b.date })} onClick={() => setBlocked((x) => x.filter((y) => y.date !== b.date))}>
                  <Emoji name="cross" size={11} />
                </IconButton>
              </Stack>
            ))}
          </Stack>
        )}
      </Box>

      <Stack direction="row" spacing={2}>
        <TextField type="number" size="small" label={t("interviewers.limit.day")} value={perDay} onChange={(e) => setPerDay(e.target.value)}
          inputProps={{ min: 0, max: 20 }} helperText={t("interviewers.limit.hint")} sx={{ maxWidth: 220 }} />
        <TextField type="number" size="small" label={t("interviewers.limit.week")} value={perWeek} onChange={(e) => setPerWeek(e.target.value)}
          inputProps={{ min: 0, max: 100 }} sx={{ maxWidth: 220 }} />
      </Stack>
      {error ? <FriendlyError error={error} compact /> : null}
      <Button variant="contained" disabled={saving || invalid} sx={{ alignSelf: "flex-start" }}
        onClick={() => onSave({ weekly_pattern: week, exceptions: blocked, max_interviews_per_day: perDay ? Number(perDay) : null, max_interviews_per_week: perWeek ? Number(perWeek) : null })}>
        {saving ? t("interviewers.saving") : t("interviewers.save")}
      </Button>
    </Stack>
  );
}
