import { useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, mfaApi } from "../api/client";

// Part 5A section 1's self-service 2FA enrollment: start -> shows the secret as text (no
// QR image library added just for this -- a manual-entry code works the same in every
// authenticator app) -> confirm with the first real code -> one-time recovery codes
// shown once. Scoped down from the spec's own fuller "2FA required for everyone" flow --
// see docs/build_log.md's own Part 5 note on why enforcement stays off by default.
export default function MfaSettingsCard() {
  const [step, setStep] = useState<"idle" | "started" | "confirmed">("idle");
  const [secret, setSecret] = useState("");
  const [provisioningUri, setProvisioningUri] = useState("");
  const [code, setCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleStart = async () => {
    setError(null);
    setLoading(true);
    try {
      const { secret: s, provisioning_uri } = await mfaApi.enrollTotpStart();
      setSecret(s);
      setProvisioningUri(provisioning_uri);
      setStep("started");
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to start enrollment"));
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    setError(null);
    setLoading(true);
    try {
      const { recovery_codes } = await mfaApi.enrollTotpConfirm(code);
      setRecoveryCodes(recovery_codes);
      setStep("confirmed");
    } catch (err) {
      setError(extractErrorMessage(err, "Incorrect code"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card variant="outlined" sx={{ maxWidth: 480 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Two-Factor Authentication
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          Add an authenticator app (TOTP) as a second sign-in step for your own account.
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {step === "idle" && (
          <Button variant="contained" onClick={handleStart} disabled={loading}>
            {loading ? "Starting..." : "Enable 2FA"}
          </Button>
        )}

        {step === "started" && (
          <Stack spacing={2}>
            <Box>
              <Typography variant="body2" fontWeight={600}>
                Manual entry code
              </Typography>
              <Typography variant="body2" fontFamily="monospace" sx={{ wordBreak: "break-all" }}>
                {secret}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Add this to your authenticator app (Google Authenticator, Authy, ...), or
                open: {provisioningUri}
              </Typography>
            </Box>
            <TextField size="small" label="6-digit code" value={code} onChange={(e) => setCode(e.target.value)} />
            <Button variant="contained" onClick={handleConfirm} disabled={loading || code.length < 6} sx={{ alignSelf: "flex-start" }}>
              {loading ? "Confirming..." : "Confirm"}
            </Button>
          </Stack>
        )}

        {step === "confirmed" && (
          <Stack spacing={2}>
            <Alert severity="success">Two-factor authentication is enabled.</Alert>
            <Box>
              <Typography variant="body2" fontWeight={600} mb={1}>
                Recovery codes (save these -- shown only once)
              </Typography>
              <Stack direction="row" flexWrap="wrap" gap={1}>
                {recoveryCodes.map((c) => (
                  <Chip key={c} label={c} size="small" sx={{ fontFamily: "monospace" }} />
                ))}
              </Stack>
            </Box>
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}
