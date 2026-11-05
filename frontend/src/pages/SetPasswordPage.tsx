import { useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { accountApi } from "../api/client";
import PublicAuthLayout from "../components/careers/PublicAuthLayout";
import { useT } from "../i18n";
import { FriendlyAnimation, FriendlyError } from "../ui-kit";

// Part 13: the one-time link a newly provisioned tenant's first admin (or any invited
// admin) receives. The token is single-use and expiring; policy is the tenant's own.

export default function SetPasswordPage() {
  const t = useT();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState(false);
  const [mismatch, setMismatch] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const submit = () => {
    if (password !== confirm) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    setError(null);
    accountApi
      .setPassword(token, password)
      .then(() => setDone(true))
      .catch((err) => setError(err));
  };

  return (
    <PublicAuthLayout illustration="secure-login" headline={t("login.setpw_headline")} tagline={t("login.setpw_tagline")}>
      <Typography variant="h1" component="h1" sx={{ fontSize: 26, mb: 2 }}>{t("login.setpw_title")}</Typography>
      {!token && <FriendlyError compact what={t("login.setpw_bad_link")} fix={t("login.setpw_bad_link_fix")} />}
      {done ? (
        <Stack spacing={2} alignItems="center" role="status" sx={{ textAlign: "center" }}>
          <FriendlyAnimation name="success" size={96} />
          <Typography sx={{ fontWeight: 700 }}>{t("login.setpw_done")}</Typography>
          <Button variant="contained" component={RouterLink} to="/login">{t("login.sign_in_link")}</Button>
        </Stack>
      ) : (
        token && (
          <Stack spacing={2} component="form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
            {error !== null && <FriendlyError error={error} compact />}
            <TextField label={t("login.setpw_new")} type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            <TextField
              label={t("login.setpw_confirm")} type="password" autoComplete="new-password" required value={confirm}
              onChange={(e) => setConfirm(e.target.value)} error={mismatch} helperText={mismatch ? t("login.setpw_mismatch") : undefined}
            />
            <Button type="submit" variant="contained" size="large" disabled={!password || !confirm}>{t("login.setpw_submit")}</Button>
          </Stack>
        )
      )}
    </PublicAuthLayout>
  );
}
