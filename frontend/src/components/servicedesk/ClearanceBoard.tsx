// X2: clearance board -- one column per team (IT, admin, finance, manager, HR), one card
// per item with its owner, status chip and "Mark done" / "Skip" actions.
import { useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import MenuItem from "@mui/material/MenuItem";
import Switch from "@mui/material/Switch";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { serviceDeskExtra, type ClearanceItem, type SeparationRow } from "../../api/serviceDeskExtra";
import { useT } from "../../i18n";
import { EmptyState, Emoji, FriendlyError, InfoTip, StatusChip } from "../../ui-kit";
import { ItemStatusChip, useDateFmt } from "./shared";

export const DEPARTMENTS = ["it", "admin", "finance", "manager", "hr"] as const;
const OPEN_ITEM = ["todo", "requested", "waiting_confirmation", "blocked", "pending"]; // feat 2026-10-06: actionable checklist statuses
const DEPT_EMOJI: Record<string, string> = { it: "laptop", admin: "building", finance: "bank", manager: "people", hr: "handshake" };
const KIND_EMOJI: Record<string, string> = { asset_recovery: "package", access_revocation: "key", knowledge_transfer: "memo", clearance: "clipboard" };

type BoardItem = ClearanceItem & { person: string; separationId: string; lwd: string | null };

export default function ClearanceBoard({ separations, canClear, onChanged, onToast }: {
  separations: SeparationRow[]; canClear: boolean; onChanged: () => void; onToast: (m: string) => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const [person, setPerson] = useState("");
  const [showDone, setShowDone] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [waive, setWaive] = useState<BoardItem | null>(null);
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState("");

  const active = separations.filter((s) => (s.items?.length ?? 0) > 0);
  const items: BoardItem[] = useMemo(() => active
    .filter((s) => !person || s.id === person)
    .flatMap((s) => (s.items ?? []).map((i) => ({ ...i, person: s.employee_name ?? s.employee_code ?? "—", separationId: s.id, lwd: s.approved_lwd })))
    .filter((i) => showDone || OPEN_ITEM.includes(i.status)), [active, person, showDone]);

  const clear = async (item: BoardItem, payload: { waive?: boolean; notes?: string | null; amount_due?: number | null }) => {
    setBusy(item.id);
    setError(null);
    try {
      await serviceDeskExtra.clearItem(item.id, payload);
      onToast(t("exits.board.cleared"));
      setWaive(null);
      onChanged();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  if (active.length === 0) return <EmptyState illustration="completed-tasks" title={t("exits.board.empty")} />;

  return (
    <Box>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }} sx={{ mb: 2 }}>
        <Typography sx={{ color: f.muted, flex: 1 }}>{t("exits.board.hint")}</Typography>
        <TextField select size="small" label={t("exits.board.person")} value={person} onChange={(e) => setPerson(e.target.value)} sx={{ minWidth: 220 }}>
          <MenuItem value="">{t("exits.board.everyone")}</MenuItem>
          {active.map((s) => <MenuItem key={s.id} value={s.id}>{s.employee_name ?? s.employee_code}</MenuItem>)}
        </TextField>
        <FormControlLabel control={<Switch checked={showDone} onChange={(e) => setShowDone(e.target.checked)} />} label={t("assets.reqs.show_done")} />
      </Stack>
      {error ? <Box sx={{ mb: 2 }}><FriendlyError error={error} compact /></Box> : null}
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", lg: "repeat(5, minmax(0, 1fr))" }, gap: 1.5, alignItems: "start" }}>
        {DEPARTMENTS.map((d) => {
          const col = items.filter((i) => i.department === d);
          const left = col.filter((i) => OPEN_ITEM.includes(i.status)).length;
          return (
            <Box key={d} component="section" aria-label={t(`exits.dept.${d}`)} sx={{ bgcolor: f.surface2, borderRadius: "16px", p: 1.25, border: `1px solid ${f.line}`, minHeight: 160 }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1, px: 0.5 }}>
                <Emoji name={DEPT_EMOJI[d]} size={18} />
                <Typography component="h3" sx={{ fontWeight: 800, flex: 1 }}>{t(`exits.dept.${d}`)}</Typography>
                <Typography sx={{ fontSize: 12, color: f.muted }}>{t("exits.board.col_count", { count: left })}</Typography>
              </Stack>
              {col.length === 0 ? (
                <Stack alignItems="center" spacing={0.5} sx={{ py: 3, color: f.muted }}>
                  <Emoji name="check" size={20} />
                  <Typography sx={{ fontSize: 13 }}>{t("exits.board.col_empty")}</Typography>
                </Stack>
              ) : (
                <Stack spacing={1}>
                  {col.map((i) => (
                    <Card key={i.id} sx={{ p: 1.25, boxShadow: "none", border: `1px solid ${f.line}`, opacity: OPEN_ITEM.includes(i.status) ? 1 : 0.75 }}>
                      <Stack direction="row" spacing={0.75} alignItems="flex-start">
                        <Emoji name={KIND_EMOJI[i.kind] ?? "clipboard"} size={16} />
                        <Typography sx={{ fontWeight: 700, fontSize: 14, flex: 1, minWidth: 0 }}>{i.title}</Typography>
                      </Stack>
                      <Typography sx={{ fontSize: 12, color: f.muted, mt: 0.5 }}>
                        {i.person}{i.lwd ? ` · ${t("exits.col.lwd")} ${fmt.date(i.lwd)}` : ""}
                      </Typography>
                      <Typography sx={{ fontSize: 12, color: f.muted }}>
                        {i.owner_name ? t("exits.board.owner", { name: i.owner_name }) : t("exits.board.owner_team", { team: t(`exits.dept.${d}`) })}
                      </Typography>
                      <Stack direction="row" spacing={0.5} sx={{ mt: 0.75 }} flexWrap="wrap" useFlexGap>
                        <ItemStatusChip status={i.status} />
                        {i.blocks_relieving && OPEN_ITEM.includes(i.status) && <StatusChip tone="coral" emoji="lock" label={t("exits.board.blocks")} />}
                      </Stack>
                      {i.status !== "pending" && i.cleared_by && (
                        <Typography sx={{ fontSize: 12, color: f.muted, mt: 0.5 }}>{t("exits.board.done_by", { name: i.cleared_by })}{i.notes ? ` · ${i.notes}` : ""}</Typography>
                      )}
                      {OPEN_ITEM.includes(i.status) && canClear && (
                        <Stack direction="row" spacing={0.5} sx={{ mt: 1 }} alignItems="center">
                          <Button size="small" variant="contained" disabled={busy === i.id} onClick={() => clear(i, {})}>{t("exits.board.clear")}</Button>
                          <Button size="small" disabled={busy === i.id} onClick={() => { setReason(""); setAmount(""); setWaive(i); }}>{t("exits.board.waive")}</Button>
                          {i.kind === "asset_recovery" && <InfoTip text={t("exits.board.asset_hint")} />}
                        </Stack>
                      )}
                    </Card>
                  ))}
                </Stack>
              )}
            </Box>
          );
        })}
      </Box>

      <Dialog open={Boolean(waive)} onClose={() => setWaive(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{waive ? t("exits.board.waive_title", { title: waive.title }) : ""}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField required label={t("exits.board.waive_reason")} placeholder={t("exits.board.waive_ph")} helperText={t("exits.board.waive_hint")}
              value={reason} onChange={(e) => setReason(e.target.value)} multiline minRows={2} />
            <TextField type="number" label={t("exits.board.amount")} placeholder={t("exits.board.amount_ph")} value={amount} onChange={(e) => setAmount(e.target.value)} inputProps={{ min: 0 }} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setWaive(null)}>{t("action.cancel")}</Button>
          <Button variant="contained" disabled={!reason.trim() || busy === waive?.id}
            onClick={() => waive && clear(waive, { waive: true, notes: reason.trim(), amount_due: amount ? Number(amount) : null })}>{t("exits.board.waive")}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
