import { useEffect, useState } from "react";
import Grid from "@mui/material/Grid";
import Skeleton from "@mui/material/Skeleton";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { peopleApi, type EmployeeHistory, type JobInfo } from "../../api/peopleApi";
import { useT } from "../../i18n";
import { FriendlyError, InfoTip, Timeline, type TimelineItem } from "../../ui-kit";
import { SectionCard, useFormatDate } from "./shared";

// History tab: every dated job record (hire, transfer, promotion...), changes still waiting
// for approval, and audited actions on this person (letters made, sensitive details viewed).

const EVENT_EMOJI: Record<string, string> = {
  hire: "waving_hand", promotion: "trophy", transfer: "building", redesignation: "id_card", manager_change: "handshake",
  confirmation: "check", probation_extension: "hourglass", compensation_change: "money", resignation: "door", termination: "door",
  retirement: "cake", rehire: "handshake", secondment: "globe", sabbatical: "coffee", suspension: "pause", contract_renewal: "memo",
};

const ACTION_EMOJI: Record<string, string> = {
  employee_created: "new", letter_generated: "page", sensitive_field_revealed: "eyes", sensitive_field_set: "lock", lifecycle_event_requested: "memo",
};

export function eventLabel(t: (k: string) => string, type?: string | null) {
  if (!type) return t("people.event.other");
  const v = t(`people.event.${type}`);
  return v === `people.event.${type}` ? type.replace(/[_-]+/g, " ") : v;
}

function recordDetail(r: JobInfo, t: (k: string, v?: Record<string, string | number>) => string): string {
  return [r.designation, r.department, r.location, r.manager_name ? t("people.history.manager", { name: r.manager_name }) : null].filter(Boolean).join(" · ");
}

export default function HistoryPanel({ employeeId }: { employeeId: string }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useFormatDate();
  const [data, setData] = useState<EmployeeHistory | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = () => {
    setError(null);
    peopleApi.history(employeeId).then(setData).catch(setError);
  };
  useEffect(load, [employeeId]);

  if (error) return <FriendlyError error={error} what={t("people.history.load_failed")} onRetry={load} />;
  if (!data) return <Skeleton variant="rounded" height={240} />;

  const jobItems: TimelineItem[] = [
    ...data.pending_changes.map((p) => ({
      id: `p-${p.id}`, emoji: "hourglass",
      title: t("people.history.pending", { what: eventLabel(t, p.event_type) }),
      meta: t("people.history.pending_meta", { date: fmt(p.effective_from), who: p.requested_by ?? "—" }),
    })),
    ...data.records.map((r) => ({
      id: r.record_id ?? `${r.effective_from}-${r.event_type}`,
      emoji: EVENT_EMOJI[r.event_type ?? ""] ?? "memo",
      title: `${eventLabel(t, r.event_type)} · ${fmt(r.effective_from)}${r.effective_to ? ` – ${fmt(r.effective_to)}` : ` · ${t("people.history.current")}`}`,
      meta: [recordDetail(r, t), r.event_reason].filter(Boolean).join(" — ") || undefined,
    })),
  ];

  const activityItems: TimelineItem[] = data.activity.map((a) => {
    const field = a.field ? t(`people.sensitive.${a.field}`) : "";
    const letter = a.letter ? t(`people.letter.${a.letter}`) : "";
    return {
      id: a.id, emoji: ACTION_EMOJI[a.action] ?? "memo",
      title: t(`people.activity.${a.action}`, { field, letter: letter.startsWith("people.") ? t("people.letter.other") : letter, what: eventLabel(t, a.event_type) }),
      meta: t("people.activity.meta", { who: a.actor ?? "—", date: fmt(a.at, true) }),
    };
  });

  return (
    <Grid container spacing={2.5}>
      <Grid size={{ xs: 12, lg: 7 }}>
        <SectionCard emoji="compass" title={t("people.history.job_title")}>
          <Timeline items={jobItems} empty={t("people.history.none")} />
        </SectionCard>
      </Grid>
      <Grid size={{ xs: 12, lg: 5 }}>
        <SectionCard emoji="eyes" title={<>{t("people.history.activity_title")}<InfoTip text={t("people.history.activity_tip")} /></>}>
          <Timeline items={activityItems} empty={t("people.history.activity_none")} />
          <Typography sx={{ fontSize: 12, color: f.muted, mt: 2 }}>{t("people.history.activity_note")}</Typography>
        </SectionCard>
      </Grid>
    </Grid>
  );
}
