import { useCallback, useEffect, useState } from "react";
import LockOpenOutlinedIcon from "@mui/icons-material/LockOpenOutlined";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage } from "../../api/client";
import { ALL_MODULES, moduleLockApi, type ModuleLockStatus } from "../../api/moduleLockApi";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { useT } from "../../i18n";
import PlatformSettingsPanel from "../PlatformSettingsPanel";

type Ask = { kind: "unlock"; module: string } | { kind: "change" } | null;

// Part 18.4: Settings > Advanced > Modules -- which modules are locked, unlock (passcode) /
// lock per module or all, change the passcode (needs the current one), and the lock settings.
export default function ModuleLockSettingsPage() {
  const t = useT();
  const { reload } = useMeBootstrap();
  const [st, setSt] = useState<ModuleLockStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [ask, setAsk] = useState<Ask>(null);
  const [passcode, setPasscode] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    moduleLockApi.status().then(setSt).catch((err) => setLoadError(extractErrorMessage(err, t("lock.err"))));
  }, [t]);
  useEffect(load, [load]);

  const close = () => { setAsk(null); setPasscode(""); setNext(""); setAgain(""); setError(null); };

  const submit = async () => {
    if (!ask) return;
    setBusy(true);
    setError(null);
    try {
      if (ask.kind === "unlock") {
        setSt(await moduleLockApi.unlock(ask.module, passcode));
        setNotice(ask.module === ALL_MODULES ? t("lock.done_all") : t("lock.done_one", { module: t(`lock.module.${ask.module}`) }));
      } else {
        await moduleLockApi.changePasscode(passcode, next);
        setNotice(t("lock.changed"));
      }
      close();
      reload();
    } catch (err) {
      setError(extractErrorMessage(err, t("lock.err")));
    } finally {
      setBusy(false);
    }
  };

  const lock = async (module: string) => {
    try {
      setSt(await moduleLockApi.lock(module));
      reload();
    } catch (err) {
      setError(extractErrorMessage(err, t("lock.err")));
    }
  };

  if (loadError) return <Alert severity="error">{loadError}</Alert>;
  if (!st) return null;
  const lockedCount = st.modules.filter((m) => m.locked).length;
  const changeInvalid = ask?.kind === "change" && (next.length < 6 || next !== again);

  return (
    <Stack spacing={2}>
      {notice && <Alert severity="success" onClose={() => setNotice(null)}>{notice}</Alert>}
      {error && !ask && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      <Card>
        <CardContent>
          <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} gap={1} mb={1}>
            <div>
              <Typography variant="h6">{t("lock.page.title")}</Typography>
              <Typography variant="body2" color="text.secondary">
                {!st.passcode_set ? t("lock.page.no_passcode") : !st.enabled ? t("lock.page.off") : t("lock.page.summary", { locked: lockedCount, total: st.modules.length })}
              </Typography>
            </div>
            {st.active && (
              <Stack direction="row" spacing={1}>
                <Button variant="contained" startIcon={<LockOpenOutlinedIcon />} disabled={lockedCount === 0} onClick={() => setAsk({ kind: "unlock", module: ALL_MODULES })}>{t("lock.unlock_all")}</Button>
                <Button variant="outlined" startIcon={<LockOutlinedIcon />} disabled={lockedCount === st.modules.length} onClick={() => lock(ALL_MODULES)}>{t("lock.lock_all")}</Button>
              </Stack>
            )}
          </Stack>
          {!st.passcode_set && <Alert severity="info" sx={{ mb: 1 }}><code>python -m hrctl.modules set-passcode --tenant &lt;company&gt;</code></Alert>}
          {st.try_again_at && <Alert severity="warning" sx={{ mb: 1 }}>{t("lock.wait", { time: new Date(st.try_again_at).toLocaleTimeString() })}</Alert>}
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("lock.col.module")}</TableCell>
                <TableCell>{t("lock.col.state")}</TableCell>
                <TableCell>{t("lock.col.since")}</TableCell>
                <TableCell align="right" />
              </TableRow>
            </TableHead>
            <TableBody>
              {st.modules.map((m) => (
                <TableRow key={m.module} hover>
                  <TableCell>{t(`lock.module.${m.module}`)}</TableCell>
                  <TableCell>
                    <Chip size="small" icon={m.locked ? <LockOutlinedIcon /> : <LockOpenOutlinedIcon />} color={m.locked ? "warning" : "success"}
                      label={m.locked ? t("lock.state.locked") : t("lock.state.open")} variant={m.locked ? "filled" : "outlined"} />
                  </TableCell>
                  <TableCell>
                    {m.unlocked_at ? `${new Date(m.unlocked_at).toLocaleString()}${m.unlocked_by ? ` · ${m.unlocked_by}` : ""}` : "—"}
                  </TableCell>
                  <TableCell align="right">
                    {st.active && (m.locked
                      ? <Button size="small" onClick={() => setAsk({ kind: "unlock", module: m.module })}>{t("lock.unlock")}</Button>
                      : <Button size="small" color="warning" onClick={() => lock(m.module)}>{t("lock.lock")}</Button>)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {st.passcode_set && (
            <Button sx={{ mt: 2 }} onClick={() => setAsk({ kind: "change" })}>{t("lock.change")}</Button>
          )}
        </CardContent>
      </Card>
      <PlatformSettingsPanel prefixes={["modules.lock."]} title={t("lock.settings_title")} />

      <Dialog open={ask !== null} onClose={busy ? undefined : close} maxWidth="xs" fullWidth>
        <DialogTitle>
          {ask?.kind === "change" ? t("lock.change") : ask?.module === ALL_MODULES ? t("lock.unlock_all") : t("lock.title", { module: ask ? t(`lock.module.${ask.module}`) : "" })}
        </DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ pt: 1 }}>
            <TextField type="password" label={ask?.kind === "change" ? t("lock.current") : t("lock.passcode")} value={passcode}
              onChange={(e) => setPasscode(e.target.value)} autoComplete="off" autoFocus fullWidth />
            {ask?.kind === "change" && (
              <>
                <TextField type="password" label={t("lock.new")} helperText={t("lock.new_hint")} value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" fullWidth />
                <TextField type="password" label={t("lock.again")} value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" fullWidth
                  error={again.length > 0 && again !== next} helperText={again.length > 0 && again !== next ? t("lock.mismatch") : " "} />
              </>
            )}
            {error && <Alert severity="error">{error}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={close} disabled={busy}>{t("lock.cancel")}</Button>
          <Button variant="contained" onClick={submit} disabled={busy || !passcode || changeInvalid}>
            {ask?.kind === "change" ? t("lock.save") : t("lock.unlock")}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
