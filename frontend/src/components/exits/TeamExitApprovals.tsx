// Part 20.3: resignations waiting for the signed-in manager (step 1 of Manager -> HR). The manager can note
// a conversation about staying, then approves; HR confirms the last working day after that.
import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { selfServiceApi, type TeamExit } from "../../api/selfServiceApi";
import { useT } from "../../i18n";
import { useDateFmt } from "../servicedesk/shared";

export default function TeamExitApprovals({ focusId, onChanged, onToast }: { focusId?: string | null; onChanged?: () => void; onToast?: (m: string) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const [items, setItems] = useState<TeamExit[]>([]);
  const [note, setNote] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { selfServiceApi.teamExits().then((r) => setItems(r.items)).catch(() => setItems([])); }, []);
  useEffect(load, [load]);
  if (!items.length) return null;
  const approve = async (id: string) => {
    setError(null);
    try {
      const r = await selfServiceApi.managerApprove(id, note[id]);
      setItems(r.items);
      onToast?.(t("me.mgr.approved"));
      onChanged?.();
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    }
  };
  return (
    <Card sx={{ p: { xs: 2, md: 2.5 }, mb: 2.25, border: "2px solid", borderColor: "warning.light" }} data-testid="team-exit-approvals">
      <Typography component="h2" sx={{ fontWeight: 800 }}>{t("me.mgr.title", { n: items.length })}</Typography>
      <Typography sx={{ fontSize: 13, color: f.muted, mb: 1.5 }}>{t("me.mgr.hint")}</Typography>
      {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
      <Stack spacing={1.5}>
        {items.map((x) => (
          <Box key={x.id} sx={{ p: 1.5, borderRadius: "12px", border: `1px solid ${x.id === focusId ? f.brand : f.line}` }}>
            <Typography sx={{ fontWeight: 700 }}>{x.employee_name} <Typography component="span" sx={{ fontSize: 12, color: f.muted }}>{x.employee_code}</Typography></Typography>
            <Typography sx={{ fontSize: 13, color: f.muted }}>
              {t("me.mgr.line", { sent: fmt.date(x.submitted_on), lwd: fmt.date(x.requested_lwd) })}{x.early_release_requested ? ` · ${t("me.resign.early_asked")}` : ""}
            </Typography>
            {x.reason_text && <Typography sx={{ fontSize: 13, mt: 0.5 }}>“{x.reason_text}”</Typography>}
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }} alignItems={{ sm: "center" }}>
              <TextField size="small" label={t("me.mgr.note")} value={note[x.id] ?? ""} onChange={(e) => setNote({ ...note, [x.id]: e.target.value })} sx={{ flex: 1 }} />
              <Button variant="contained" onClick={() => approve(x.id)}>{t("me.mgr.approve")}</Button>
            </Stack>
          </Box>
        ))}
      </Stack>
    </Card>
  );
}
