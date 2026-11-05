import { useState } from "react";
import type { FormEvent } from "react";
import { Link as RouterLink, useLocation, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { useAuth } from "../auth/AuthContext";
import { useBootstrap } from "../bootstrap/BootstrapContext";
import PublicAuthLayout from "../components/careers/PublicAuthLayout";
import { useT } from "../i18n";
import { FriendlyError } from "../ui-kit";

export default function LoginPage() {
  const { login } = useAuth();
  const { productName } = useBootstrap();
  const t = useT();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  const from = (location.state as { from?: string } | null)?.from || "/";

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <PublicAuthLayout illustration="secure-login" headline={t("login.headline", { name: productName })} tagline={t("login.tagline")}>
      <Typography variant="h1" component="h1" sx={{ fontSize: 26 }}>{t("login.title")}</Typography>
      <Typography sx={{ color: "text.secondary", mt: 0.5, mb: 3 }}>{t("login.subtitle", { name: productName })}</Typography>
      <Box component="form" onSubmit={handleSubmit} noValidate={false}>
        <Stack spacing={2}>
          {error !== null && <FriendlyError error={error} what={t("login.failed")} fix={t("login.failed_fix")} compact />}
          <TextField label={t("login.email")} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} fullWidth autoFocus />
          <TextField label={t("login.password")} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} fullWidth />
          <Button type="submit" variant="contained" size="large" disabled={loading} fullWidth>
            {loading ? t("login.signing_in") : t("login.submit")}
          </Button>
          <Typography variant="body2" textAlign="center">
            {t("login.no_account")}{" "}
            <Link component={RouterLink} to="/register">
              {t("login.register_link")}
            </Link>
          </Typography>
        </Stack>
      </Box>
    </PublicAuthLayout>
  );
}
