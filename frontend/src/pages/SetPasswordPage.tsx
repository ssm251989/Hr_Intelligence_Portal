import { useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { accountApi, extractErrorMessage } from "../api/client";

// Part 13: the one-time link a newly provisioned tenant's first admin (or any invited
// admin) receives. The token is single-use and expiring; policy is the tenant's own.

export default function SetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (password !== confirm) {
      setError("The two passwords don't match.");
      return;
    }
    accountApi
      .setPassword(token, password)
      .then(() => setDone(true))
      .catch((err) => setError(extractErrorMessage(err, "Could not set the password")));
  };

  return (
    <Box sx={{ display: "flex", justifyContent: "center", mt: 8, px: 2 }}>
      <Card sx={{ width: "100%", maxWidth: 420 }}>
        <CardContent>
          <Typography variant="h5" component="h1" gutterBottom>Set your password</Typography>
          {!token && <Alert severity="error">This link is incomplete. Use the full link from your invitation email.</Alert>}
          {done ? (
            <Alert severity="success">
              Password set. <Link component={RouterLink} to="/login">Sign in</Link>
            </Alert>
          ) : (
            token && (
              <Stack spacing={2} component="form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
                {error && <Alert severity="error">{error}</Alert>}
                <TextField label="New password" type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
                <TextField label="Confirm password" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                <Button type="submit" variant="contained" disabled={!password || !confirm}>Set password</Button>
              </Stack>
            )
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
