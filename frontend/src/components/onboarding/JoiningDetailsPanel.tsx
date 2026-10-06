import { useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { onboardingExtraApi, type JoiningDetailsHr } from "../../api/onboardingExtra";
import { useI18n } from "../../i18n";
import { EmptyState, StatusChip } from "../../ui-kit";
import { useDateText } from "./shared";

// Change 2026-10-05: HR's view of a joiner's details. Empty fields are listed as "not filled yet"
// (never errors); "Remind candidate" emails the joiner the list with their welcome link; "Lock"
// stops further edits. Bank / PAN / Aadhaar stay masked (last 4); the audited reveal is on the
// employee record.

const SECTION_KEYS: Record<string, string> = {
  personal: "wsteps.g.personal", address: "wsteps.g.address", emergency: "wsteps.g.emergency", bank_id: "wsteps.g.bank",
};

export default function JoiningDetailsPanel({ caseId, details, canEdit, onChanged }: {
  caseId: string; details: JoiningDetailsHr | null | undefined; canEdit: boolean; onChanged: () => void;
}) {
  const f = useTheme().palette.fresh;
  const { t } = useI18n();
  const d = useDateText();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (!details) return <EmptyState compact illustration="fill-forms" title={t("jform.hr.none")} />;
  const empty = new Set([...details.missing_required, ...details.missing_optional]);
  const sections = Object.keys(SECTION_KEYS).map((key) => ({ key, fields: details.fields.filter((x) => x.section === key) })).filter((s) => s.fields.length);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      onChanged();
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, "") });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Stack spacing={2} data-testid="hr-joining-details">
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        {details.status === "submitted" ? <StatusChip tone="ok" emoji="check" label={t("jform.hr.sent")} />
          : details.status === "draft" ? <StatusChip tone="sun" emoji="memo" label={t("jform.hr.draft")} />
            : <StatusChip tone="muted" emoji="hourglass" label={t("jform.hr.not_started")} />}
        {details.locked && <StatusChip tone="sky" emoji="lock" label={t("jform.hr.locked")} />}
        <Typography sx={{ fontSize: 13, color: f.muted }}>
          {t("jform.hr.empty_count", { n: empty.size, required: details.missing_required.length })}
        </Typography>
      </Stack>
      {msg && <Alert severity={msg.ok ? "success" : "warning"} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      {canEdit && (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Button variant="contained" size="small" disabled={busy || empty.size === 0 || details.locked}
            onClick={() => act(() => onboardingExtraApi.remindDetails(caseId), t("jform.hr.reminded"))}>{t("jform.hr.remind")}</Button>
          <Button variant="outlined" size="small" disabled={busy}
            onClick={() => act(() => onboardingExtraApi.lockDetails(caseId, !details.locked), details.locked ? t("jform.hr.unlocked_msg") : t("jform.hr.locked_msg"))}>
            {details.locked ? t("jform.hr.unlock") : t("jform.hr.lock")}
          </Button>
        </Stack>
      )}
      {details.last_reminder_at && <Typography sx={{ fontSize: 12, color: f.muted }}>{t("jform.hr.last_reminder", { when: d.when(details.last_reminder_at) })}</Typography>}
      {sections.map((s) => (
        <Box key={s.key}>
          <Typography component="h3" sx={{ fontWeight: 700, mb: 0.75 }}>{t(SECTION_KEYS[s.key])}</Typography>
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 0.75 }}>
            {s.fields.map((x) => (
              <Box key={x.key} sx={{ p: 1, borderRadius: "10px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                <Typography sx={{ fontSize: 12, color: f.muted }}>{x.label}{x.required ? " *" : ""}</Typography>
                {empty.has(x.key)
                  ? <Typography sx={{ fontSize: 14, color: f.muted, fontStyle: "italic" }}>{t("jform.hr.not_filled")}</Typography>
                  : <Typography sx={{ fontSize: 14, fontWeight: 600, wordBreak: "break-word" }}>{x.value}</Typography>}
              </Box>
            ))}
          </Box>
        </Box>
      ))}
    </Stack>
  );
}
