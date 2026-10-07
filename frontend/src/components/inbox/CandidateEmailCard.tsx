import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonBase from "@mui/material/ButtonBase";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { candidateEmailsApi, type CandidateEmailItem } from "../../api/candidateEmailsApi";
import { useI18n } from "../../i18n";
import { localeTag } from "../interviews/weekDates";
import Emoji from "../../ui-kit/Emoji";
import StatusChip, { type Tone } from "../../ui-kit/StatusChip";
import UserAvatar from "../../ui-kit/UserAvatar";

// Part 17.7: what each email is about, in plain words (+ emoji, never colour alone).
const TOPICS: Record<string, { emoji: string; tone: Tone }> = {
  interview_time: { emoji: "calendar", tone: "sky" },
  documents: { emoji: "page", tone: "brand" },
  question: { emoji: "question", tone: "sun" },
  offer: { emoji: "handshake", tone: "ok" },
  withdrawal: { emoji: "door", tone: "coral" },
  automated: { emoji: "robot", tone: "muted" },
  other: { emoji: "speech", tone: "muted" },
};

export function TopicChip({ topic }: { topic?: string | null }) {
  const { t } = useI18n();
  const key = topic && TOPICS[topic] ? topic : "other";
  return <StatusChip tone={TOPICS[key].tone} emoji={TOPICS[key].emoji} label={t(`candidateEmails.topic.${key}`)} />;
}

// One email = one card: who, which job, what it's about (one line), when, and the next step.
export default function CandidateEmailCard({
  email, selected, busy, onSelect, onReply, onToggleDone, onAssign, onLinked,
}: {
  email: CandidateEmailItem;
  selected: boolean;
  busy?: boolean;
  onSelect: () => void;
  onReply: () => void;
  onToggleDone: (done: boolean) => void;
  onAssign: () => void;
  onLinked?: () => void;
}) {
  const f = useTheme().palette.fresh;
  const { t, locale } = useI18n();
  const fmt = new Intl.DateTimeFormat(localeTag(locale), { dateStyle: "medium", timeStyle: "short" });
  const linked = Boolean(email.candidate_id);
  const done = email.status === "done";
  const who = email.candidate_name || email.from_address;
  const summary = email.summary?.trim() || email.subject || t("inbox.no_subject");

  return (
    <Box
      sx={{
        borderRadius: "14px", border: `1px solid ${selected ? f.brand : f.line}`, bgcolor: selected ? f.brandSoft : f.surface,
        opacity: done && !selected ? 0.85 : 1, overflow: "hidden",
      }}
    >
      <ButtonBase
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        aria-label={t("candidateEmails.card.open_label", { who, summary })}
        sx={{
          width: "100%", textAlign: "left", display: "flex", gap: 1.25, alignItems: "flex-start", p: 1.5,
          "&:hover": { bgcolor: selected ? f.brandSoft : f.surface2 }, "&:focus-visible": { outline: `2px solid ${f.brand}`, outlineOffset: -2 },
        }}
      >
        <UserAvatar name={who} size={40} />
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Stack direction="row" justifyContent="space-between" spacing={1} alignItems="baseline">
            <Typography sx={{ fontWeight: 700, fontSize: 15, wordBreak: "break-word" }}>{who}</Typography>
            <Typography sx={{ color: f.muted, fontSize: 12, flexShrink: 0 }}>{email.received_at ? fmt.format(new Date(email.received_at)) : ""}</Typography>
          </Stack>
          <Typography sx={{ color: f.muted, fontSize: 13 }} noWrap>
            {linked ? email.job_title || t("candidateEmails.card.no_job") : t("candidateEmails.card.not_matched_from", { from: email.from_address })}
          </Typography>
          <Stack direction="row" spacing={0.75} alignItems="flex-start" sx={{ mt: 0.75 }}>
            <Typography sx={{ fontSize: 14, flex: 1, minWidth: 0, wordBreak: "break-word" }}>{summary}</Typography>
            {email.summary_source === "ai" && (
              <Tooltip title={t("candidateEmails.card.ai_tip")}>
                <Box component="span" aria-label={t("candidateEmails.card.ai_tip")}
                  sx={{ flexShrink: 0, fontSize: 11, fontWeight: 800, px: 0.75, py: 0.1, borderRadius: 999, bgcolor: f.skySoft, color: f.sky }}>
                  {t("candidateEmails.card.ai")}
                </Box>
              </Tooltip>
            )}
          </Stack>
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
            <TopicChip topic={email.topic} />
            {done ? (
              <StatusChip tone="ok" emoji="check" label={t("candidateEmails.card.done")} />
            ) : (
              <StatusChip tone="sun" emoji="hourglass" label={t("candidateEmails.card.needs_action")} />
            )}
            {!linked && <StatusChip tone="sun" emoji="question" label={t("candidateEmails.card.not_linked")} />}
            {linked && email.match_rule && <StatusChip tone="muted" emoji="link" label={t(`candidateEmails.rule.${email.match_rule}`)} />}
          </Stack>
        </Box>
      </ButtonBase>
      {/* Part 22.2: several candidates matched -- HR picks; the app never guesses between two */}
      {!linked && (email.suggestions?.length ?? 0) > 0 && (
        <Box sx={{ px: 1.5, pb: 1, pl: { sm: 7.5 } }}>
          <Typography sx={{ fontSize: 12, fontWeight: 700, color: f.muted, mb: 0.5 }}>{t("candidateEmails.suggested")}</Typography>
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
            {email.suggestions!.filter((s) => s.application_id).map((s) => (
              <Button key={s.candidate_id} size="small" variant="outlined" disabled={busy}
                onClick={() => candidateEmailsApi.link(email.id, s.application_id!, true).then(() => onLinked?.())}>
                {t("candidateEmails.link_to", { name: s.name ?? s.email ?? "?" })}{s.job_title ? ` (${s.job_title})` : ""}
              </Button>
            ))}
          </Stack>
        </Box>
      )}
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ px: 1.5, pb: 1.5, pl: { sm: 7.5 } }}>
        {linked && email.application_id && (
          <Button size="small" variant="outlined" component={RouterLink} to={`/candidates/${email.application_id}`} startIcon={<Emoji name="technologist" size={16} />}>
            {t("candidateEmails.action.open_candidate")}
          </Button>
        )}
        {!linked && (
          <Button size="small" variant="contained" onClick={onAssign} startIcon={<Emoji name="link" size={16} />}>
            {t("candidateEmails.action.assign")}
          </Button>
        )}
        {linked && email.application_id ? (
          <Button size="small" variant="outlined" onClick={onReply} startIcon={<Emoji name="envelope" size={16} />}>
            {t("candidateEmails.action.reply")}
          </Button>
        ) : (
          <Button size="small" variant="outlined" component="a"
            href={`mailto:${email.from_address}?subject=${encodeURIComponent(email.subject ? (email.subject.toLowerCase().startsWith("re:") ? email.subject : `Re: ${email.subject}`) : "")}`}
            startIcon={<Emoji name="envelope" size={16} />}>
            {t("candidateEmails.action.reply")}
          </Button>
        )}
        <Button size="small" variant={done ? "text" : "outlined"} color={done ? "inherit" : "primary"} disabled={busy} onClick={() => onToggleDone(!done)}
          startIcon={<Emoji name={done ? "pause" : "check"} size={16} />}>
          {done ? t("candidateEmails.action.not_done") : t("candidateEmails.action.mark_done")}
        </Button>
      </Stack>
    </Box>
  );
}
