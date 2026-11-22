// Part 32: where the company stands with CTD Techs. The waiting page (locked install) and Settings > Licence.
// - not set up: "This copy isn't set up by CTD Techs" + Load CTD file (ctd_config.json + .sig from CTD)
// - locked: the request (number, text, Email CTD / Copy request) + the code entry; "Send request" when none is open
// - approved / grace: the state, the end date, the one CTD approver, the code entry for a pending request
import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { extractErrorMessage } from "../../api/client";
import { licenceApi, type LicenceStatus } from "../../api/licenceApi";
import { useT } from "../../i18n";
import CtdRequestBox from "./CtdRequestBox";

export default function LicencePanel({ waiting = false, onUnlocked }: { waiting?: boolean; onUnlocked?: () => void }) {
  const t = useT();
  const [s, setS] = useState<LicenceStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [cfg, setCfg] = useState<File | null>(null);
  const [sig, setSig] = useState<File | null>(null);

  const load = useCallback(() => licenceApi.status().then(setS).catch((e) => setMsg({ ok: false, text: extractErrorMessage(e, t("lic.error")) })), [t]);
  useEffect(() => { void load(); }, [load]);

  const run = async (fn: () => Promise<string | null>) => {
    setBusy(true);
    setMsg(null);
    try {
      const text = await fn();
      if (text) setMsg({ ok: true, text });
      await load();
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, t("lic.error")) });
    } finally {
      setBusy(false);
    }
  };

  if (!s) return <Box sx={{ display: "grid", placeItems: "center", py: 6 }}>{msg ? <Alert severity="error">{msg.text}</Alert> : <CircularProgress />}</Box>;

  const req = s.request && s.request.status === "pending" ? s.request : null;
  const loadForm = (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
      <Button variant="outlined" component="label">{cfg ? cfg.name : t("lic.pick_config")}
        <input hidden type="file" accept=".json,application/json" onChange={(e) => setCfg(e.target.files?.[0] ?? null)} /></Button>
      <Button variant="outlined" component="label">{sig ? sig.name : t("lic.pick_signature")}
        <input hidden type="file" accept=".sig,text/plain" onChange={(e) => setSig(e.target.files?.[0] ?? null)} /></Button>
      <Button variant="contained" disabled={busy || !cfg || !sig}
        onClick={() => void run(async () => { const r = await licenceApi.loadConfig(cfg!, sig!); return t("lic.config_loaded", { email: r.approver }); })}>
        {t("lic.load_config")}
      </Button>
    </Stack>
  );
  const stateChip = { approved: { c: "success" as const, k: "lic.state.approved" }, grace: { c: "warning" as const, k: "lic.state.grace" },
    locked: { c: "error" as const, k: "lic.state.locked" } }[s.state];

  return (
    <Card sx={{ p: 3, maxWidth: 760 }}>
      <Stack spacing={2}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 800 }}>{waiting ? t("lic.waiting_title") : t("lic.title")}</Typography>
          <Typography variant="body2" color="text.secondary">{waiting ? t("lic.waiting_intro") : t("lic.intro")}</Typography>
        </Box>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center">
          <Chip color={stateChip.c} label={t(stateChip.k)} />
          {s.state === "grace" && s.grace_days_left != null && <Chip variant="outlined" label={t("lic.grace_days", { days: s.grace_days_left })} />}
          {s.valid_until && <Chip variant="outlined" label={t(s.expired ? "lic.ended_on" : "lic.valid_until", { date: s.valid_until })} />}
          {s.approver && <Typography variant="body2" color="text.secondary">{t("lic.approver", { email: s.approver })}</Typography>}
        </Stack>
        {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}
        {s.expired && <Alert severity="error">{t("lic.expired_body")}</Alert>}
        {!s.expired && s.expiring_in_days != null && <Alert severity="warning">{t("lic.expiring_body", { days: s.expiring_in_days })}</Alert>}
        {s.state === "grace" && <Alert severity="warning">{t("lic.grace_body", { days: s.grace_days_left ?? 0 })}</Alert>}

        {!s.is_admin ? (
          s.state === "locked" && <Alert severity="info">{t("lic.ask_admin")}</Alert>
        ) : !s.set_up ? (
          <Stack spacing={1.5}>
            <Alert severity="error">{t("lic.not_set_up")}</Alert>
            {loadForm}
          </Stack>
        ) : req ? (
          <Stack spacing={1.5}>
            <Typography variant="body2">
              {t(req.kind === "access" ? "lic.request_access_line" : "lic.request_modules_line", { number: req.number ?? "" })}
              {req.delivery === "sent" ? ` ${t("lic.sent_by_mail")}` : ` ${t("lic.send_yourself")}`}
            </Typography>
            <CtdRequestBox requestText={req.request_text} mailto={req.mailto} approver={req.approver} busy={busy} locked={req.locked_until}
              onCode={(code) => void run(async () => {
                const r = await licenceApi.enterCode(code);
                onUnlocked?.();
                return r.kind === "access" ? t("lic.unlocked") : t("lic.modules_on", { names: r.names });
              })} />
          </Stack>
        ) : s.state !== "approved" ? (
          <Button variant="contained" disabled={busy} sx={{ alignSelf: "flex-start" }}
            onClick={() => void run(async () => { await licenceApi.requestAccess(); return t("lic.request_made"); })}>{t("lic.send_request_btn")}</Button>
        ) : null}
        {s.is_admin && s.install_id && <Typography variant="caption" color="text.secondary">{t("lic.install_id", { id: s.install_id })}</Typography>}
        {s.is_admin && s.set_up && !waiting && (
          <Stack spacing={1}>
            <Typography variant="caption" color="text.secondary">{t("lic.change_approver_note")}</Typography>
            {loadForm}
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
