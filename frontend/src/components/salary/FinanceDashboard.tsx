import Alert from "@mui/material/Alert";

import { useT } from "../../i18n";

// Part 18.15: the department finance dashboard (filled in by 18.15).
export default function FinanceDashboard() {
  const t = useT();
  return <Alert severity="info">{t("salaryx.finance_soon")}</Alert>;
}
