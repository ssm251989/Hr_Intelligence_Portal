import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import IconButton from "@mui/material/IconButton";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import MoreHorizIcon from "@mui/icons-material/MoreHoriz";
import { useTheme } from "@mui/material/styles";

import type { JoinerCard as JoinerCardData } from "../../api/onboardingExtra";
import { useT } from "../../i18n";
import { Emoji, ProgressRing, StatusChip, UserAvatar } from "../../ui-kit";
import { JoinerStatusChip, useDateText } from "./shared";

export type JoinerAction = "open" | "joined" | "date" | "link" | "no_show" | "revoke" | "declined";

// One joiner: who, what role, when, how ready (ring), and what needs doing. A joiner who
// starts within 3 days and is not fully ready gets the coral "not ready" styling.
export default function JoinerCard({
  card, canEdit, canApprove, onAction, busy,
}: {
  card: JoinerCardData;
  canEdit: boolean;
  canApprove: boolean;
  onAction: (action: JoinerAction, card: JoinerCardData) => void;
  busy?: boolean;
}) {
  const f = useTheme().palette.fresh;
  const t = useT();
  const d = useDateText();
  const [menu, setMenu] = useState<HTMLElement | null>(null);
  const alert = card.not_ready_soon;
  const tone = card.readiness_percent >= 100 ? "ok" : alert ? "coral" : card.readiness_percent >= 60 ? "brand" : "sun";

  const whenText =
    card.days_to_join < 0 ? t("onboarding.card.was_due", { count: -card.days_to_join })
      : card.days_to_join === 0 ? t("onboarding.card.today")
        : t("onboarding.card.in_days", { count: card.days_to_join });

  const pick = (a: JoinerAction) => {
    setMenu(null);
    onAction(a, card);
  };

  return (
    <Card
      component="article"
      aria-label={t("onboarding.card.aria", { name: card.name })}
      sx={{
        p: 2.25, display: "flex", flexDirection: "column", gap: 1.5, height: "100%",
        border: `1px solid ${alert ? f.coral : "transparent"}`, bgcolor: alert ? f.coralSoft : f.surface,
      }}
    >
      <Stack direction="row" spacing={1.5} alignItems="flex-start">
        <UserAvatar name={card.name} size={48} />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontWeight: 800, fontSize: 16 }} noWrap title={card.name}>{card.name}</Typography>
          <Typography sx={{ color: f.muted, fontSize: 13 }} noWrap>
            {[card.role, card.department].filter(Boolean).join(" · ") || t("onboarding.card.no_role")}
          </Typography>
          <Typography sx={{ fontSize: 13, mt: 0.5 }}>
            <Emoji name="calendar" size={14} /> <b>{d.day(card.joining_date)}</b> · {whenText}
          </Typography>
        </Box>
        <ProgressRing
          value={card.readiness_percent} size={72} thickness={9} tone={tone}
          label={`${card.readiness_percent}%`}
          caption={t("onboarding.card.ring", { percent: card.readiness_percent, name: card.name })}
        />
      </Stack>

      <Stack direction="row" spacing={0.75} sx={{ flexWrap: "wrap", rowGap: 0.75 }}>
        <JoinerStatusChip status={card.status} t={t} />
        {card.documents_waiting > 0 && <StatusChip tone="sun" emoji="page" label={t("onboarding.card.docs_waiting", { count: card.documents_waiting })} />}
        {card.overdue_tasks > 0 && <StatusChip tone="coral" emoji="fire" label={t("onboarding.card.tasks_late", { count: card.overdue_tasks })} />}
        {card.link_expired && <StatusChip tone="coral" emoji="link" label={t("onboarding.card.link_expired")} />}
      </Stack>

      <Typography sx={{ fontSize: 13, color: f.muted }}>
        {card.readiness.total > 0
          ? t("onboarding.card.steps_done", { done: card.readiness.done, total: card.readiness.total })
          : t("onboarding.card.no_steps")}
      </Typography>

      {alert && (
        <Box role="alert" sx={{ display: "flex", gap: 1, alignItems: "center", fontSize: 13, fontWeight: 700, color: f.coral }}>
          <Emoji name="warning" size={16} />
          {t("onboarding.card.not_ready", { count: Math.max(card.days_to_join, 0) })}
        </Box>
      )}

      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: "auto" }}>
        <Button variant="outlined" size="small" onClick={() => onAction("open", card)}>{t("onboarding.card.open")}</Button>
        {canApprove && (
          <Button
            variant="contained" size="small" disabled={!card.allowed_actions.includes("mark_joined") || busy} onClick={() => onAction("joined", card)}
            title={card.can_mark_joined ? undefined : t("onboarding.card.joined_later")}
          >
            <Emoji name="party" size={16} />&nbsp;{t("onboarding.card.mark_joined")}
          </Button>
        )}
        <Box sx={{ flex: 1 }} />
        {canEdit && (
          <>
            <IconButton aria-label={t("onboarding.card.more", { name: card.name })} onClick={(e) => setMenu(e.currentTarget)} size="small">
              <MoreHorizIcon />
            </IconButton>
            <Menu anchorEl={menu} open={Boolean(menu)} onClose={() => setMenu(null)}>
              <MenuItem onClick={() => pick("date")}><Emoji name="calendar" size={16} />&nbsp; {t("onboarding.action.change_date")}</MenuItem>
              <MenuItem onClick={() => pick("link")}><Emoji name="link" size={16} />&nbsp; {t("onboarding.action.new_link")}</MenuItem>
              {/* fix 2026-10-05: only what the server accepts for this stage (withdraw is never offered after joining) */}
              {card.allowed_actions.includes("no_show") && (
                <MenuItem onClick={() => pick("no_show")}><Emoji name="pause" size={16} />&nbsp; {t("onboarding.action.no_show")}</MenuItem>
              )}
              {card.allowed_actions.includes("candidate_declined") && (
                <MenuItem onClick={() => pick("declined")}><Emoji name="speech" size={16} />&nbsp; {t("joinerx.action.declined")}</MenuItem>
              )}
              {card.allowed_actions.includes("withdraw_offer") && (
                <MenuItem onClick={() => pick("revoke")} sx={{ color: f.coral }}><Emoji name="cross" size={16} />&nbsp; {t("onboarding.action.revoke")}</MenuItem>
              )}
            </Menu>
          </>
        )}
      </Stack>
    </Card>
  );
}
