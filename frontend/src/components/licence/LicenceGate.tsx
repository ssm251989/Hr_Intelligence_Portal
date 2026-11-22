// Part 32: the app shell asks once where the company stands. Locked -> only the waiting page (nothing else opens);
// grace / ending soon / ended -> a banner for everyone, with a link to Settings > Licence for administrators.
import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import { Link as RouterLink } from "react-router-dom";

import { licenceApi, type LicenceStatus } from "../../api/licenceApi";
import { useT } from "../../i18n";

export function useLicenceStatus(signedIn: boolean) {
  const [status, setStatus] = useState<LicenceStatus | null>(null);
  const reload = useCallback(() => {
    if (!signedIn) return;
    licenceApi.status().then(setStatus).catch(() => setStatus(null)); // an older server without the licence API: no gate
  }, [signedIn]);
  useEffect(reload, [reload]);
  return { status, reload };
}

export function LicenceBanner({ status }: { status: LicenceStatus | null }) {
  const t = useT();
  if (!status) return null;
  const action = status.is_admin ? <Button color="inherit" size="small" component={RouterLink} to="/settings/advanced/licence">{t("lic.open")}</Button> : undefined;
  if (status.expired) return <Alert severity="error" action={action} sx={{ mb: 2 }}>{t("lic.expired_body")}</Alert>;
  if (status.state === "grace") return <Alert severity="warning" action={action} sx={{ mb: 2 }}>{t("lic.grace_body", { days: status.grace_days_left ?? 0 })}</Alert>;
  if (status.expiring_in_days != null) return <Alert severity="warning" action={action} sx={{ mb: 2 }}>{t("lic.expiring_body", { days: status.expiring_in_days })}</Alert>;
  return null;
}
