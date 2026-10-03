import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, superAdminApi } from "../../api/client";
import type { ConsoleActivationRequest } from "../../api/modulesApi";
import { useT } from "../../i18n";
import { StatusChip } from "../../ui-kit";

// Part 19.2 (CTD Techs console): module activation requests from every installation, with
// resend email / new code / cancel. Codes are never stored -- "new code" shows one ONCE here.
export default function ActivationRequestsCard({ token }: { token: string }) {
  const t = useT();
  const [rows, setRows] = useState<ConsoleActivationRequest[] | null>(null);
  const [approvers, setApprovers] = useState<string[]>([]);
  const [msg, setMsg] = useState<{ tone: "success" | "error" | "info"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    superAdminApi.activationRequests(token).then((r) => { setRows(r.requests); setApprovers(r.approvers); })
      .catch((err) => setMsg({ tone: "error", text: extractErrorMessage(err, t("act.err")) }));
  }, [token, t]);
  useEffect(load, [load]);

  const act = async (id: string, fn: () => Promise<{ code?: string; email_error?: string | null; status?: string }>, done: string) => {
    setBusy(id);
    setMsg(null);
    try {
      const r = await fn();
      if (r.code) setMsg({ tone: "info", text: t("act.code_shown", { code: r.code }) });
      else setMsg(r.email_error ? { tone: "error", text: t("act.email_failed", { reason: r.email_error }) } : { tone: "success", text: done });
      load();
    } catch (err) {
      setMsg({ tone: "error", text: extractErrorMessage(err, t("act.err")) });
    } finally {
      setBusy(null);
    }
  };

  const status = (s: ConsoleActivationRequest["status"]) =>
    s === "pending" ? <StatusChip tone="sun" emoji="hourglass" label={t("act.status.pending")} />
      : s === "activated" ? <StatusChip status="done" label={t("act.status.activated")} />
      : <StatusChip tone="muted" label={t(`act.status.${s}`)} />;

  return (
    <Card sx={{ p: 0, mt: 3 }}>
      <Box sx={{ p: 2.5, pb: 1 }}>
        <Typography variant="h6">{t("act.title")}</Typography>
        <Typography variant="body2" color="text.secondary">{t("act.intro", { approvers: approvers.join(", ") || "—" })}</Typography>
      </Box>
      {msg && <Alert severity={msg.tone} sx={{ mx: 2.5, mb: 1 }} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      {rows && rows.length === 0 ? (
        <Typography sx={{ p: 2.5 }} color="text.secondary">{t("act.empty")}</Typography>
      ) : (
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("act.col.company")}</TableCell>
                <TableCell>{t("act.col.modules")}</TableCell>
                <TableCell>{t("act.col.by")}</TableCell>
                <TableCell>{t("act.col.status")}</TableCell>
                <TableCell align="right">{t("console.col.actions")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(rows ?? []).map((r) => (
                <TableRow key={r.id} hover>
                  <TableCell>
                    <Typography sx={{ fontWeight: 700 }}>{r.company ?? r.tenant}</Typography>
                    <Typography variant="caption" color="text.secondary">{r.installation}</Typography>
                  </TableCell>
                  <TableCell>{r.module_names}</TableCell>
                  <TableCell>
                    <Typography variant="body2">{r.requested_by_name || r.requested_by}</Typography>
                    <Typography variant="caption" color="text.secondary">{r.requested_at ? new Date(r.requested_at).toLocaleString() : ""}</Typography>
                  </TableCell>
                  <TableCell>
                    {status(r.status)}
                    {r.email_error && <Typography variant="caption" color="error" sx={{ display: "block" }}>{t("act.not_emailed")}</Typography>}
                  </TableCell>
                  <TableCell align="right">
                    {(r.status === "pending" || r.status === "expired") && (
                      <Stack direction="row" spacing={1} justifyContent="flex-end">
                        <Button size="small" variant="outlined" disabled={busy === r.id} onClick={() => void act(r.id, () => superAdminApi.activationResend(token, r.id), t("act.resent"))}>{t("act.resend")}</Button>
                        <Button size="small" variant="outlined" disabled={busy === r.id} onClick={() => void act(r.id, () => superAdminApi.activationNewCode(token, r.id), "")}>{t("act.new_code")}</Button>
                        {r.status === "pending" && (
                          <Button size="small" color="warning" variant="outlined" disabled={busy === r.id}
                            onClick={() => void act(r.id, () => superAdminApi.activationCancel(token, r.id), t("act.cancelled"))}>{t("act.cancel")}</Button>
                        )}
                      </Stack>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Card>
  );
}
