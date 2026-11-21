import { useEffect, useState } from "react";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import { superAdminApi } from "../../api/client";
import { useT } from "../../i18n";
import { formatDateTime } from "../../utils/datetime";

type Row = Awaited<ReturnType<typeof superAdminApi.signups>>["signups"][number];
const TONE: Record<string, "default" | "info" | "warning" | "success" | "error"> = {
  pending_email: "default", confirmed: "info", provisioning: "info", waiting_approval: "warning", active: "success", failed: "error", expired: "default",
};

/** Part 28.5: every online sign-up for CTD Techs - who, which address, where it stands (and why it failed). */
export default function SignupsConsole({ token }: { token: string }) {
  const t = useT();
  const [rows, setRows] = useState<Row[] | null>(null);
  useEffect(() => { superAdminApi.signups(token).then((r) => setRows(r.signups)).catch(() => setRows([])); }, [token]);
  return (
    <Card sx={{ p: 2, mt: 3 }}>
      <Typography variant="h6" sx={{ mb: 1 }}>{t("su28.title")}</Typography>
      {rows && rows.length === 0 ? <Typography color="text.secondary">{t("su28.none")}</Typography> : (
        <Table size="small">
          <TableHead><TableRow><TableCell>Company</TableCell><TableCell>Address</TableCell><TableCell>Admin</TableCell><TableCell>Modules</TableCell>
            <TableCell>Status</TableCell><TableCell>Signed up</TableCell></TableRow></TableHead>
          <TableBody>
            {(rows ?? []).map((r) => (
              <TableRow key={r.id}>
                <TableCell>{r.company}</TableCell>
                <TableCell>{r.host}</TableCell>
                <TableCell>{r.admin_name}<br /><Typography variant="caption">{r.admin_email}</Typography></TableCell>
                <TableCell>{r.modules.join(", ") || "—"}</TableCell>
                <TableCell><Chip size="small" color={TONE[r.status] ?? "default"} label={r.status.replace(/_/g, " ")} />
                  {r.error && <Typography variant="caption" color="error" sx={{ display: "block" }}>{r.error}</Typography>}</TableCell>
                <TableCell>{formatDateTime(r.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
