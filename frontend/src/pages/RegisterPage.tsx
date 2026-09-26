import { useState } from "react";
import type { FormEvent } from "react";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Link from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { PUBLIC_REGISTRABLE_ROLES } from "../api/types";
import type { UserRole } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useBootstrap } from "../bootstrap/BootstrapContext";
import PublicAuthLayout from "../components/careers/PublicAuthLayout";
import { useT } from "../i18n";
import { FriendlyError, humanise } from "../ui-kit";

export default function RegisterPage() {
  const { register } = useAuth();
  const { productName } = useBootstrap();
  const t = useT();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole | "">("");
  const [error, setError] = useState<unknown>(null);
  const [roleMissing, setRoleMissing] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!role) {
      setRoleMissing(true);
      return;
    }
    setRoleMissing(false);
    setLoading(true);
    try {
      await register({ email, password, full_name: fullName || null, role });
      navigate("/jobs", { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  const roleLabel = (r: string) => {
    const key = `login.role.${r}`;
    const text = t(key);
    return text !== key ? text : humanise(r);
  };

  return (
    <PublicAuthLayout illustration="hello" headline={t("login.register_headline", { name: productName })} tagline={t("login.register_tagline")}>
      <Typography variant="h1" component="h1" sx={{ fontSize: 26 }}>{t("login.register_title")}</Typography>
      <Typography sx={{ color: "text.secondary", mt: 0.5, mb: 3 }}>{t("login.register_subtitle")}</Typography>
      <Box component="form" onSubmit={handleSubmit}>
        <Stack spacing={2}>
          {error !== null && <FriendlyError error={error} compact />}
          <TextField label={t("login.full_name")} autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} fullWidth autoFocus />
          <TextField label={t("login.email")} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} fullWidth />
          <TextField label={t("login.password")} type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} helperText={t("login.password_help")} fullWidth />
          <TextField
            select
            label={t("login.role")}
            required
            value={role}
            onChange={(e) => {
              setRole(e.target.value as UserRole);
              setRoleMissing(false);
            }}
            error={roleMissing}
            helperText={roleMissing ? t("login.role_missing") : undefined}
            fullWidth
          >
            {PUBLIC_REGISTRABLE_ROLES.map((r) => (
              <MenuItem key={r} value={r}>
                {roleLabel(r)}
              </MenuItem>
            ))}
          </TextField>
          <Button type="submit" variant="contained" size="large" disabled={loading} fullWidth>
            {loading ? t("login.registering") : t("login.register_submit")}
          </Button>
          <Typography variant="body2" textAlign="center">
            {t("login.have_account")}{" "}
            <Link component={RouterLink} to="/login">
              {t("login.sign_in_link")}
            </Link>
          </Typography>
        </Stack>
      </Box>
    </PublicAuthLayout>
  );
}
