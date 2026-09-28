import { useState } from "react";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { moduleLockApi } from "../../api/moduleLockApi";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { useT } from "../../i18n";

// Part 18.4: shown instead of a page whose module is locked. Admins type the module passcode
// here (unlocks this module for the whole company until an admin locks it again); everyone
// else is told to ask an admin.
export default function LockedModuleCard({ module }: { module: string }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { can, reload } = useMeBootstrap();
  const isAdmin = can("platform.settings.configure");
  const [passcode, setPasscode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const name = t(`lock.module.${module}`);

  const unlock = async () => {
    setBusy(true);
    setError(null);
    try {
      await moduleLockApi.unlock(module, passcode);
      setPasscode("");
      reload();
    } catch (err) {
      setError(extractErrorMessage(err, t("lock.err")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box sx={{ display: "grid", placeItems: "center", minHeight: "60vh", px: 2 }}>
      <Card sx={{ p: { xs: 3, sm: 4 }, maxWidth: 460, width: "100%", textAlign: "center" }}>
        <Box sx={{ width: 64, height: 64, borderRadius: "20px", bgcolor: f.brandSoft, color: f.brand, display: "grid", placeItems: "center", mx: "auto", mb: 2 }}>
          <LockOutlinedIcon sx={{ fontSize: 34 }} />
        </Box>
        <Typography variant="h2" sx={{ fontSize: 22, mb: 1 }}>{t("lock.title", { module: name })}</Typography>
        <Typography sx={{ color: f.muted, mb: 2.5 }}>{isAdmin ? t("lock.body_admin") : t("lock.body_user")}</Typography>
        {isAdmin && (
          <Stack
            component="form"
            spacing={1.5}
            onSubmit={(e) => {
              e.preventDefault();
              if (passcode) void unlock();
            }}
          >
            <TextField type="password" label={t("lock.passcode")} value={passcode} onChange={(e) => setPasscode(e.target.value)} autoComplete="off" autoFocus fullWidth />
            {error && <Alert severity="error" sx={{ textAlign: "left" }}>{error}</Alert>}
            <Button type="submit" variant="contained" size="large" disabled={!passcode || busy}>{busy ? t("lock.unlocking") : t("lock.unlock")}</Button>
          </Stack>
        )}
      </Card>
    </Box>
  );
}
