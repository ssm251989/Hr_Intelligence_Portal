import { useMemo } from "react";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonBase from "@mui/material/ButtonBase";
import Card from "@mui/material/Card";
import IconButton from "@mui/material/IconButton";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";

import type { InterviewListRow } from "../../api/types";
import { useI18n } from "../../i18n";
import { useReducedMotion } from "../../ui-kit/motion";
import { InterviewStatusChip } from "../InterviewChips";
import { addDays, localeTag, sameDay } from "./weekDates";

// Part 15 / spec I1: a week calendar of interviews -- day columns, hour rows, one block per
// interview (a real button, so Tab walks through them in time order and Enter opens one).
// On a phone the same week is shown as a day-by-day agenda instead of a squeezed grid.

const HOUR_PX = 52;
const BLOCK_HOURS = 1; // interviews don't store an end time; show a one-hour slot

interface Placed {
  row: InterviewListRow;
  at: Date;
  lane: number;
  lanes: number;
}

function placeDay(rows: { row: InterviewListRow; at: Date }[]): Placed[] {
  const sorted = [...rows].sort((a, b) => a.at.getTime() - b.at.getTime());
  const placed: Placed[] = [];
  let group: Placed[] = [];
  let groupEnd = 0;
  const flush = () => {
    const lanes = Math.max(1, ...group.map((p) => p.lane + 1));
    group.forEach((p) => (p.lanes = lanes));
    group = [];
  };
  for (const item of sorted) {
    const start = item.at.getTime();
    if (group.length && start >= groupEnd) flush();
    const laneEnds = new Map<number, number>();
    group.forEach((p) => laneEnds.set(p.lane, Math.max(laneEnds.get(p.lane) ?? 0, p.at.getTime() + BLOCK_HOURS * 3600e3)));
    let lane = 0;
    while ((laneEnds.get(lane) ?? 0) > start) lane += 1;
    const p: Placed = { row: item.row, at: item.at, lane, lanes: 1 };
    group.push(p);
    placed.push(p);
    groupEnd = Math.max(groupEnd, start + BLOCK_HOURS * 3600e3);
  }
  flush();
  return placed;
}

export default function InterviewWeekCalendar({
  weekStart,
  onWeekChange,
  rows,
  loading,
  onOpen,
}: {
  weekStart: Date;
  onWeekChange: (weekStart: Date) => void;
  rows: InterviewListRow[];
  loading: boolean;
  onOpen: (row: InterviewListRow) => void;
}) {
  const theme = useTheme();
  const f = theme.palette.fresh;
  const { t, locale } = useI18n();
  const tag = localeTag(locale);
  const reduced = useReducedMotion();
  const narrow = useMediaQuery(theme.breakpoints.down("md"));
  const today = new Date();
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart]);

  const { byDay, unscheduled, startHour, endHour, count } = useMemo(() => {
    const buckets: { row: InterviewListRow; at: Date }[][] = days.map(() => []);
    const noTime: InterviewListRow[] = [];
    let minH = 9;
    let maxH = 18;
    let n = 0;
    for (const row of rows) {
      if (!row.scheduled_at) {
        noTime.push(row);
        continue;
      }
      const at = new Date(row.scheduled_at);
      const idx = days.findIndex((d) => sameDay(d, at));
      if (idx < 0) continue;
      buckets[idx].push({ row, at });
      minH = Math.min(minH, at.getHours());
      maxH = Math.max(maxH, Math.min(24, at.getHours() + BLOCK_HOURS + (at.getMinutes() ? 1 : 0)));
      n += 1;
    }
    return { byDay: buckets.map(placeDay), unscheduled: noTime, startHour: minH, endHour: maxH, count: n };
  }, [rows, days]);

  const hours = Array.from({ length: endHour - startHour }, (_, i) => startHour + i);
  const timeFmt = new Intl.DateTimeFormat(tag, { hour: "numeric", minute: "2-digit" });
  const dayFmt = new Intl.DateTimeFormat(tag, { weekday: "short" });
  const longDayFmt = new Intl.DateTimeFormat(tag, { weekday: "long", day: "numeric", month: "long" });
  const rangeFmt = new Intl.DateTimeFormat(tag, { day: "numeric", month: "short", year: "numeric" });
  const hourLabel = (h: number) => timeFmt.format(new Date(2000, 0, 1, h, 0));
  const weekLabel = `${rangeFmt.format(days[0])} – ${rangeFmt.format(days[6])}`;

  const blockLabel = (p: { row: InterviewListRow; at: Date }) =>
    t("interviews.week.block_label", {
      name: p.row.candidate_name || t("interviews.unnamed"),
      job: p.row.job_title,
      time: `${longDayFmt.format(p.at)} ${timeFmt.format(p.at)}`,
      status: t(`interviews.status.${p.row.status}`),
    });

  const header = (
    <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ xs: "flex-start", sm: "center" }} justifyContent="space-between" sx={{ mb: 2 }}>
      <Box>
        <Typography component="h2" sx={{ fontWeight: 800, fontSize: 18 }} aria-live="polite">
          {weekLabel}
        </Typography>
        <Typography sx={{ color: f.muted, fontSize: 13 }}>
          {count === 1 ? t("interviews.week.count_one") : t("interviews.week.count", { count })}
        </Typography>
      </Box>
      <Stack direction="row" spacing={1} alignItems="center">
        <Tooltip title={t("interviews.week.prev")}>
          <IconButton aria-label={t("interviews.week.prev")} onClick={() => onWeekChange(addDays(weekStart, -7))} sx={{ border: `1px solid ${f.line}` }}>
            <ChevronLeftIcon />
          </IconButton>
        </Tooltip>
        <Button variant="outlined" onClick={() => onWeekChange(new Date())}>
          {t("interviews.week.today")}
        </Button>
        <Tooltip title={t("interviews.week.next")}>
          <IconButton aria-label={t("interviews.week.next")} onClick={() => onWeekChange(addDays(weekStart, 7))} sx={{ border: `1px solid ${f.line}` }}>
            <ChevronRightIcon />
          </IconButton>
        </Tooltip>
      </Stack>
    </Stack>
  );

  const blockSx = {
    display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 0.5, textAlign: "left", width: "100%",
    borderRadius: "10px", p: 0.75, bgcolor: f.skySoft, color: f.ink, borderLeft: `3px solid ${f.sky}`, overflow: "hidden",
    transition: reduced ? "none" : "box-shadow 150ms ease",
    "&:hover": { boxShadow: f.shadowHover },
    "&:focus-visible": { outline: `2px solid ${f.brand}`, outlineOffset: 2 },
  } as const;

  if (loading) {
    return (
      <Card sx={{ p: 2.25 }}>
        {header}
        <Skeleton variant="rounded" height={360} />
      </Card>
    );
  }

  if (narrow) {
    return (
      <Card sx={{ p: 2 }}>
        {header}
        <Stack spacing={2}>
          {days.map((d, i) => (
            <Box key={i} component="section" aria-label={longDayFmt.format(d)}>
              <Typography sx={{ fontWeight: 700, color: sameDay(d, today) ? f.brand : f.ink, mb: 1 }}>
                {longDayFmt.format(d)}
                {sameDay(d, today) ? ` · ${t("interviews.week.today")}` : ""}
              </Typography>
              {byDay[i].length === 0 ? (
                <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("interviews.week.free_day")}</Typography>
              ) : (
                <Stack spacing={1}>
                  {byDay[i].map((p) => (
                    <ButtonBase key={p.row.interview_id} onClick={() => onOpen(p.row)} aria-label={blockLabel(p)} sx={blockSx}>
                      <Typography sx={{ fontWeight: 700, fontSize: 13 }}>
                        {timeFmt.format(p.at)} · {p.row.candidate_name || t("interviews.unnamed")}
                      </Typography>
                      <Typography sx={{ fontSize: 12, color: f.muted }}>{p.row.job_title}</Typography>
                      <InterviewStatusChip status={p.row.status} />
                    </ButtonBase>
                  ))}
                </Stack>
              )}
            </Box>
          ))}
        </Stack>
        <Unscheduled rows={unscheduled} onOpen={onOpen} />
      </Card>
    );
  }

  return (
    <Card sx={{ p: 2.25 }}>
      {header}
      <Box sx={{ overflowX: "auto" }}>
        <Box role="region" aria-label={t("interviews.week.grid_label", { week: weekLabel })} sx={{ display: "grid", gridTemplateColumns: "64px repeat(7, minmax(110px, 1fr))", minWidth: 840 }}>
          {/* column headings */}
          <Box sx={{ display: "contents" }}>
            <Box aria-hidden />
            {days.map((d, i) => {
              const isToday = sameDay(d, today);
              return (
                <Box key={i} aria-current={isToday ? "date" : undefined}
                  sx={{ textAlign: "center", py: 1, borderRadius: "10px 10px 0 0", bgcolor: isToday ? f.brandSoft : "transparent", color: isToday ? f.brand : f.ink }}>
                  <Typography sx={{ fontSize: 12, fontWeight: 600, color: isToday ? f.brand : f.muted, textTransform: "uppercase" }}>{dayFmt.format(d)}</Typography>
                  <Typography sx={{ fontSize: 20, fontWeight: 800, lineHeight: 1.1 }}>{d.getDate()}</Typography>
                </Box>
              );
            })}
          </Box>
          {/* hour labels + day columns */}
          <Box sx={{ display: "contents" }}>
            <Box aria-hidden sx={{ position: "relative", height: hours.length * HOUR_PX }}>
              {hours.map((h, i) => (
                <Typography key={h} sx={{ position: "absolute", top: i * HOUR_PX - 8, right: 8, fontSize: 11, color: f.muted, fontVariantNumeric: "tabular-nums" }}>
                  {hourLabel(h)}
                </Typography>
              ))}
            </Box>
            {days.map((d, i) => (
              <Box key={i} role="group" aria-label={longDayFmt.format(d)}
                sx={{
                  position: "relative", height: hours.length * HOUR_PX, borderLeft: `1px solid ${f.line}`,
                  bgcolor: sameDay(d, today) ? f.surface2 : "transparent",
                  backgroundImage: `repeating-linear-gradient(to bottom, ${f.line} 0, ${f.line} 1px, transparent 1px, transparent ${HOUR_PX}px)`,
                }}>
                {byDay[i].map((p) => {
                  const top = (p.at.getHours() - startHour + p.at.getMinutes() / 60) * HOUR_PX;
                  const width = 100 / p.lanes;
                  return (
                    <ButtonBase key={p.row.interview_id} onClick={() => onOpen(p.row)} aria-label={blockLabel(p)}
                      sx={{ ...blockSx, position: "absolute", top: top + 2, left: `calc(${p.lane * width}% + 3px)`, width: `calc(${width}% - 6px)`, height: BLOCK_HOURS * HOUR_PX - 4, zIndex: 1 }}>
                      <Typography sx={{ fontWeight: 700, fontSize: 12, lineHeight: 1.2, width: "100%" }} noWrap>
                        {timeFmt.format(p.at)} · {p.row.candidate_name || t("interviews.unnamed")}
                      </Typography>
                      <InterviewStatusChip status={p.row.status} />
                    </ButtonBase>
                  );
                })}
              </Box>
            ))}
          </Box>
        </Box>
      </Box>
      <Unscheduled rows={unscheduled} onOpen={onOpen} />
    </Card>
  );
}

function Unscheduled({ rows, onOpen }: { rows: InterviewListRow[]; onOpen: (row: InterviewListRow) => void }) {
  const f = useTheme().palette.fresh;
  const { t } = useI18n();
  if (rows.length === 0) return null;
  return (
    <Box sx={{ mt: 2 }}>
      <Typography sx={{ fontWeight: 700, mb: 1 }}>{t("interviews.week.no_time", { count: rows.length })}</Typography>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
        {rows.map((row) => (
          <Button key={row.interview_id} size="small" variant="outlined" onClick={() => onOpen(row)} sx={{ borderColor: f.line }}>
            {row.candidate_name || t("interviews.unnamed")} · {row.job_title}
          </Button>
        ))}
      </Stack>
    </Box>
  );
}
