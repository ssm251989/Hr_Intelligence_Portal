import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { Link as RouterLink } from "react-router-dom";

import type { RecentJoiner } from "../../api/onboardingExtra";
import { useT } from "../../i18n";
import { Emoji, StatusChip, UserAvatar } from "../../ui-kit";
import { useFresh } from "../candidates/stages";
import type { JoinerDialogKind } from "./JoinerActionDialog";

// Fix 2026-10-05: people who joined in the last 90 days (and anyone marked "not reporting").
// After joining, the offer can't be withdrawn -- only Not reporting / Absconded / Resigned / Terminated.

const ACTIONS: { kind: JoinerDialogKind; emoji: string; labelKey: string }[] = [
  { kind: "not_reporting", emoji: "warning", labelKey: "joinerx.action.not_reporting" },
  { kind: "stop_not_reporting", emoji: "check", labelKey: "joinerx.action.stop_not_reporting" },
  { kind: "absconded", emoji: "door", labelKey: "joinerx.action.absconded" },
  { kind: "resigned", emoji: "waving_hand", labelKey: "joinerx.action.resigned" },
  { kind: "terminated", emoji: "cross", labelKey: "joinerx.action.terminated" },
];
const NOTICE: Record<string, { labelKey: string }> = {
  reminder: { labelKey: "joinerx.notice.reminder" }, show_cause: { labelKey: "joinerx.notice.show_cause" }, final: { labelKey: "joinerx.notice.final" },
};

export default function RecentJoiners({ rows, canAct, onAct }: { rows: RecentJoiner[]; canAct: boolean; onAct: (r: RecentJoiner, kind: JoinerDialogKind) => void }) {
  const t = useT();
  const f = useFresh();
  const [menu, setMenu] = useState<{ el: HTMLElement; row: RecentJoiner } | null>(null);
  return (
    <Card component="section" aria-labelledby="recent-joiners" sx={{ p: 2.25 }}>
      <Typography id="recent-joiners" component="h2" sx={{ fontWeight: 800, fontSize: 17, mb: 0.5, display: "flex", alignItems: "center", gap: 1 }}>
        <Emoji name="party" size={20} /> {t("joinerx.recent.title")}
        <Typography component="span" sx={{ color: f.muted, fontWeight: 500, fontSize: 13 }}>{t("onboarding.group.count", { count: rows.length })}</Typography>
      </Typography>
      <Typography sx={{ color: f.muted, fontSize: 13, mb: 1.5 }}>{t("joinerx.recent.hint")}</Typography>
      <Stack component="ul" spacing={1} sx={{ listStyle: "none", p: 0, m: 0 }}>
        {rows.map((r) => {
          const flow = r.not_reporting?.status === "active" ? r.not_reporting : null;
          const acts = ACTIONS.filter((a) => r.allowed_actions.includes(a.kind as never));
          return (
            <Box component="li" key={r.case_id} sx={{ display: "flex", alignItems: "center", gap: 1.5, p: 1.25, borderRadius: "12px", bgcolor: flow ? f.coralSoft : f.surface2, flexWrap: "wrap" }}>
              <UserAvatar name={r.name} size={36} />
              <Box sx={{ flex: 1, minWidth: 180 }}>
                <Typography sx={{ fontWeight: 700 }}>
                  {r.candidate_id ? <RouterLink to={`/candidates/list?q=${encodeURIComponent(r.name)}`} style={{ color: "inherit" }}>{r.name}</RouterLink> : r.name}
                </Typography>
                <Typography sx={{ fontSize: 13, color: f.muted }}>
                  {[r.role, t("joinerx.recent.since", { days: r.days_since_joining, date: new Date(`${r.joining_date}T00:00:00`).toLocaleDateString() })].filter(Boolean).join(" · ")}
                </Typography>
                {flow && (
                  <Typography sx={{ fontSize: 13, color: f.coral, fontWeight: 700 }}>
                    {t("joinerx.recent.not_reporting", { date: new Date(`${flow.last_seen}T00:00:00`).toLocaleDateString() })}
                    {flow.notices.length ? ` · ${flow.notices.map((n) => (NOTICE[n] ? t(NOTICE[n].labelKey) : n)).join(", ")}` : ` · ${t("joinerx.recent.no_notice_yet")}`}
                  </Typography>
                )}
              </Box>
              <StatusChip tone={flow ? "coral" : "ok"} emoji={flow ? "warning" : "check"} label={flow ? t("joinerx.recent.chip_not_reporting") : t("onboarding.status.joined")} />
              {canAct && acts.length > 0 && (
                <Button size="small" variant="outlined" onClick={(e) => setMenu({ el: e.currentTarget, row: r })} aria-label={t("joinerx.recent.actions_for", { name: r.name })}>
                  {t("joinerx.recent.actions")}
                </Button>
              )}
            </Box>
          );
        })}
      </Stack>
      <Menu anchorEl={menu?.el} open={Boolean(menu)} onClose={() => setMenu(null)}>
        {menu && ACTIONS.filter((a) => menu.row.allowed_actions.includes(a.kind as never)).map((a) => (
          <MenuItem key={a.kind} onClick={() => { const row = menu.row; setMenu(null); onAct(row, a.kind); }}
            sx={a.kind === "absconded" || a.kind === "terminated" ? { color: f.coral } : undefined}>
            <Emoji name={a.emoji} size={16} />&nbsp; {t(a.labelKey)}
          </MenuItem>
        ))}
      </Menu>
    </Card>
  );
}
