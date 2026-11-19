import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { http } from "../api/client";
import PublicAuthLayout from "../components/careers/PublicAuthLayout";
import { useT } from "../i18n";
import { FriendlyError } from "../ui-kit";

// L1 (Part 27): "Forgot password?" -> a one-time link (30 min) by email. The answer is the same whether the
// email has an account or not. Without a connected mailbox the page says to ask the HR admin, who can send a
// reset link (or copy it) from Settings > People & access.
export default function ForgotPasswordPage() {
  const t = useT();
  const [available, setAvailable] = useState<boolean | null>(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    http.get<{ email_reset: boolean }>("/auth/forgot-password").then((r) => setAvailable(r.email_reset)).catch(() => setAvailable(false));
  }, []);

  const submit = async () => {
    setBusy(true); setError(null);
    try { await http.post("/auth/forgot-password", { email }); setDone(true); } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <PublicAuthLayout illustration="secure-login" headline={t("forgot.headline")} tagline={t("forgot.tagline")}>
      <Typography variant="h1" component="h1" sx={{ fontSize: 26, mb: 2 }}>{t("forgot.title")}</Typography>
      {available === false ? (
        <Alert severity="info">{t("forgot.ask_admin")}</Alert>
      ) : done ? (
        <Alert severity="success" role="status">{t("forgot.sent")}</Alert>
      ) : (
        <Stack spacing={2} component="form" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
          {error !== null && <FriendlyError error={error} compact />}
          <Typography sx={{ color: "text.secondary" }}>{t("forgot.intro")}</Typography>
          <TextField label={t("login.email")} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
          <Button type="submit" variant="contained" size="large" disabled={busy || !email.includes("@") || available === null}>{t("forgot.submit")}</Button>
        </Stack>
      )}
      <Typography variant="body2" textAlign="center" sx={{ mt: 2 }}>
        <Link component={RouterLink} to="/login">{t("forgot.back")}</Link>
      </Typography>
    </PublicAuthLayout>
  );
}
