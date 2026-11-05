// Part 20.3: HR reviews an employee's own profile change requests (approve -> saved; reject needs a reason).
import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage } from "../../api/client";
import { selfServiceApi, type ChangeRequest } from "../../api/selfServiceApi";
import { useT } from "../../i18n";
import { ChangeList } from "../../pages/MyProfilePage";

export default function ChangeRequestsCard({ employeeId, canEdit, onChanged }: { employeeId: string; canEdit: boolean; onChanged: () => void }) {
  const t = useT();
  const [items, setItems] = useState<ChangeRequest[]>([]);
  const [note, setNote] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { selfServiceApi.changeRequests(employeeId).then((r) => setItems(r.items)).catch(() => setItems([])); }, [employeeId]);
  useEffect(load, [load]);
  if (!items.length) return null;
  const act = async (id: string, approve: boolean) => {
    setError(null);
    try {
      await selfServiceApi.review(id, approve, note[id]);
      load();
      onChanged();
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    }
  };
  return (
    <Card sx={{ p: { xs: 2, md: 2.5 }, mb: 2, border: "2px solid", borderColor: "warning.light" }} data-testid="hr-change-requests">
      <Typography component="h2" sx={{ fontWeight: 800, mb: 1 }}>{t("me.cr.hr_title", { n: items.length })}</Typography>
      {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
      <Stack spacing={1.5}>
        {items.map((r) => (
          <Box key={r.id}>
            <ChangeList items={[r]} />
            {canEdit && (
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }} alignItems={{ sm: "center" }}>
                <TextField size="small" label={t("me.cr.review_note")} value={note[r.id] ?? ""} onChange={(e) => setNote({ ...note, [r.id]: e.target.value })} sx={{ flex: 1 }} />
                <Button variant="contained" color="success" onClick={() => act(r.id, true)}>{t("me.cr.approve")}</Button>
                <Button variant="outlined" color="error" onClick={() => act(r.id, false)}>{t("me.cr.reject")}</Button>
              </Stack>
            )}
          </Box>
        ))}
      </Stack>
    </Card>
  );
}
