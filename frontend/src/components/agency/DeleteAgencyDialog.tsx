import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Typography from "@mui/material/Typography";

import { extractErrorMessage } from "../../api/client";
import { agencyApi, type AgencyDeleteCheck } from "../../api/agencyApi";
import { useT } from "../../i18n";

// Part 22.5: Delete agency -- no history -> removed; history (candidates / BGV cases / fees) -> deactivated and hidden,
// history kept, restorable from the Inactive filter. Open BGV cases must be reassigned or cancelled first.
export default function DeleteAgencyDialog({ agency, onClose, onDone }: {
  agency: { id: string; name: string } | null; onClose: () => void; onDone: (result: "deleted" | "deactivated") => void;
}) {
  const t = useT();
  const [check, setCheck] = useState<AgencyDeleteCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setCheck(null);
    setError(null);
    if (agency) agencyApi.deleteCheck(agency.id).then(setCheck).catch((e) => setError(extractErrorMessage(e, t("ag22.err"))));
  }, [agency, t]);

  const go = async () => {
    if (!agency) return;
    setBusy(true);
    try {
      const r = await agencyApi.remove(agency.id);
      onDone(r.result);
    } catch (e) {
      setError(extractErrorMessage(e, t("ag22.err")));
    } finally {
      setBusy(false);
    }
  };

  const blocked = (check?.open_bgv.length ?? 0) > 0;
  return (
    <Dialog open={Boolean(agency)} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{t("ag22.title", { name: agency?.name ?? "" })}</DialogTitle>
      <DialogContent>
        {!check && !error ? <Box sx={{ display: "grid", placeItems: "center", py: 3 }}><CircularProgress /></Box> : null}
        {check && blocked && (
          <Alert severity="warning" sx={{ mb: 1 }}>
            {t("ag22.open_bgv")}
            <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
              {check.open_bgv.map((c) => <li key={c.id}>{c.candidate ?? "?"} - {t(`bv21.st.${c.status}`)}</li>)}
            </Box>
          </Alert>
        )}
        {check && !blocked && (check.mode === "delete"
          ? <Typography>{t("ag22.delete_text")}</Typography>
          : <Typography>{t("ag22.deactivate_text", { candidates: check.candidates, cases: check.bgv_cases })}</Typography>)}
        {check && !blocked && check.members > 0 && <Typography sx={{ mt: 1, fontSize: 13 }}>{t("ag22.logins", { n: check.members })}</Typography>}
        {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("ag22.cancel")}</Button>
        <Button color="error" variant="contained" onClick={go} disabled={!check || blocked || busy}>
          {check?.mode === "deactivate" ? t("ag22.deactivate") : t("ag22.delete")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
