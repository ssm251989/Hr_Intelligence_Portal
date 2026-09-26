import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { offersExtraApi, type OfferTimelineResponse } from "../../api/offersExtra";
import { useT } from "../../i18n";
import { StageStepper, StatusChip, Timeline, type TimelineItem } from "../../ui-kit";
import { useWhen } from "./shared";

// L-B8: sent -> viewed -> signed (-> joined), built from the offer's own status + the
// audit trail. L-B7: the expiry date is always spelled out (default 7 days after sending).
// K-H4: any approval steps attached to this offer. K-H5: how the signature is collected.

const EMOJI: Record<string, string> = { sent: "envelope", viewed: "eyes", signed: "writing_hand", joined: "party", esign_failed: "warning" };

function daysUntil(iso: string): number {
  const end = new Date(`${iso}T23:59:59`);
  return Math.ceil((end.getTime() - Date.now()) / 86_400_000);
}

export default function OfferTimeline({ applicationId, status, signed, reloadKey }: { applicationId: string; status: string; signed: boolean; reloadKey: string }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const when = useWhen();
  const [data, setData] = useState<OfferTimelineResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    offersExtraApi
      .offerTimeline(applicationId)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setFailed(false);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [applicationId, reloadKey]);

  const events = data?.events ?? [];
  const has = (k: string) => events.some((e) => e.kind === k);
  const isSigned = signed || has("signed");
  const joined = status === "onboarding_completed" || has("joined");
  const viewed = has("viewed") || isSigned;
  const current = joined ? 3 : isSigned ? 3 : viewed ? 2 : 1;
  const stages = [t("offers.tl.stage_sent"), t("offers.tl.stage_viewed"), t("offers.tl.stage_signed"), t("offers.tl.stage_joined")];

  const items: TimelineItem[] = events.map((e, i) => ({
    id: `${e.kind}-${i}`,
    emoji: EMOJI[e.kind] ?? "label",
    title: t(`offers.tl.${e.kind}`),
    meta: [when(e.at), e.by && e.by !== "system" ? t("offers.tl.by", { who: e.by }) : ""].filter(Boolean).join(" · "),
  }));
  if (!has("viewed") && !isSigned) {
    items.push({ id: "viewed-unknown", emoji: "eyes", title: t("offers.tl.viewed_unknown"), meta: t("offers.tl.viewed_unknown_hint") });
  }

  const offer = data?.offer;
  const expiry = offer?.expiry_date ?? null;
  const left = expiry ? daysUntil(expiry) : null;

  return (
    <Box>
      <Box sx={{ mb: 2 }}>
        <StageStepper stages={stages} current={Math.min(current, stages.length - 1)} />
      </Box>
      {failed && <Typography sx={{ fontSize: 13, color: f.muted, mb: 1 }}>{t("offers.tl.failed")}</Typography>}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 7 }}>
          <Timeline items={items} empty={t("offers.tl.empty")} />
        </Grid>
        <Grid size={{ xs: 12, md: 5 }}>
          <Stack spacing={1.5}>
            {expiry && !isSigned && (
              <Box>
                <Typography sx={{ fontSize: 12, color: f.muted, fontWeight: 600 }}>{t("offers.expiry.label")}</Typography>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                  <Typography sx={{ fontWeight: 800 }}>{when(expiry, false)}</Typography>
                  {left != null && left < 0 ? (
                    <StatusChip tone="coral" emoji="fire" label={t("offers.expiry.expired")} />
                  ) : left != null && left <= 2 ? (
                    <StatusChip tone="sun" emoji="alarm_clock" label={t("offers.expiry.days_left", { count: left })} />
                  ) : (
                    <StatusChip tone="sky" emoji="calendar" label={t("offers.expiry.days_left", { count: left ?? 0 })} />
                  )}
                </Stack>
                {offer?.expiry_is_default && (
                  <Typography sx={{ fontSize: 12, color: f.muted }}>{t("offers.expiry.default", { count: data?.expiry_days ?? 7 })}</Typography>
                )}
              </Box>
            )}
            {offer?.joining_date && (
              <Box>
                <Typography sx={{ fontSize: 12, color: f.muted, fontWeight: 600 }}>{t("offers.joining_date")}</Typography>
                <Typography sx={{ fontWeight: 800 }}>{when(offer.joining_date, false)}</Typography>
              </Box>
            )}
            {offer && (
              <Box>
                <Typography sx={{ fontSize: 12, color: f.muted, fontWeight: 600 }}>{t("offers.esign.label")}</Typography>
                {offer.esign === "docusign" ? (
                  <StatusChip tone="sky" emoji="writing_hand" label={t("offers.esign.online")} />
                ) : (
                  <StatusChip tone="muted" emoji="pencil" label={t("offers.esign.manual")} />
                )}
              </Box>
            )}
            {data && data.approvals.length > 0 && (
              <Box>
                <Typography sx={{ fontSize: 12, color: f.muted, fontWeight: 600, mb: 0.5 }}>{t("offers.approvals.title")}</Typography>
                <Stack spacing={0.75} component="ol" sx={{ m: 0, pl: 2.5 }}>
                  {data.approvals.map((a) => (
                    <li key={a.id}>
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                        <Typography sx={{ fontSize: 14, fontWeight: 600 }}>{a.name}</Typography>
                        <StatusChip status={a.action === "approve" ? "approved" : a.action === "reject" ? "rejected" : a.status} />
                        {a.acted_by && <Typography sx={{ fontSize: 12, color: f.muted }}>{t("offers.tl.by", { who: a.acted_by })}</Typography>}
                      </Stack>
                    </li>
                  ))}
                </Stack>
              </Box>
            )}
          </Stack>
        </Grid>
      </Grid>
    </Box>
  );
}
