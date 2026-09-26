import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { offersExtraApi, type BgvTimelineResponse } from "../../api/offersExtra";
import { useT } from "../../i18n";
import { StatusChip, Timeline, type TimelineItem } from "../../ui-kit";
import { useWhen } from "../offers/shared";

// L-B5: document + vendor updates arrive on their own; shown here as a timeline, newest last.
// `reloadKey` changes whenever the card's status / documents change so the list follows along.

const EMOJI: Record<string, string> = {
  bgv_requested: "shield", bgv_document_uploaded: "page", ai_document_validator_scored: "robot", bgv_clearance_decision: "writing_hand",
  vendor_created: "building", vendor_consent: "handshake", vendor_started: "rocket", vendor_completed: "clipboard", vendor_decided: "writing_hand",
};

const CHECK_STATUS: Record<string, string> = { clear: "valid", discrepancy: "needs_review", unable_to_verify: "failed", pending: "pending", in_progress: "in_progress" };

export default function BgvTimeline({ applicationId, reloadKey }: { applicationId: string; reloadKey: string }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const when = useWhen();
  const [data, setData] = useState<BgvTimelineResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    offersExtraApi
      .bgvTimeline(applicationId)
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

  if (failed) return <Typography sx={{ fontSize: 13, color: f.muted }}>{t("bgv.timeline.failed")}</Typography>;
  if (!data) return <Typography sx={{ fontSize: 13, color: f.muted }}>{t("offers.shared.loading")}</Typography>;

  const docLabel = (type?: string | null) => (type ? (t(`bgv.doc.${type}`) !== `bgv.doc.${type}` ? t(`bgv.doc.${type}`) : type) : "");
  const items: TimelineItem[] = data.events.map((e, i) => {
    let title = t(`bgv.timeline.${e.kind}`, { doc: docLabel(e.doc_type) });
    if (e.kind === "bgv_clearance_decision" || e.kind === "vendor_decided") title = t(`bgv.timeline.decision_${e.decision === "reject" ? "reject" : "clear"}`);
    if (e.kind === "ai_document_validator_scored" && e.result) title = `${title} — ${t(`status.${e.result}`)}`;
    const by = e.by && e.by !== "system" ? t("bgv.timeline.by", { who: e.by }) : "";
    return { id: `${e.kind}-${i}`, emoji: EMOJI[e.kind] ?? "label", title, meta: [when(e.at), by].filter(Boolean).join(" · ") };
  });

  return (
    <Box>
      <Timeline items={items} empty={t("bgv.timeline.empty")} />
      {data.vendor_cases.map((c) => (
        <Box key={c.id} sx={{ mt: 2 }}>
          <Typography sx={{ fontWeight: 700, fontSize: 13, mb: 1 }}>{t("bgv.vendor.title")}</Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {c.checks.map((ch) => (
              <Stack key={ch.type} direction="row" spacing={0.75} alignItems="center" sx={{ p: 0.75, pl: 1.25, borderRadius: 999, border: `1px solid ${f.line}` }}>
                <Typography sx={{ fontSize: 13, fontWeight: 600 }}>{t(`bgv.vendor.check.${ch.type}`)}</Typography>
                <StatusChip status={CHECK_STATUS[ch.status] ?? ch.status} />
              </Stack>
            ))}
          </Stack>
          {c.discrepancy && (
            <Typography sx={{ fontSize: 13, mt: 1, color: f.sunInk }}>{t("bgv.vendor.discrepancy", { text: c.discrepancy })}</Typography>
          )}
        </Box>
      ))}
    </Box>
  );
}
