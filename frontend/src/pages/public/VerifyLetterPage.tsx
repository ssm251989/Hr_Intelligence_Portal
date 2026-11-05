import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useParams } from "react-router-dom";

import { http } from "../../api/client";
import { LanguagePicker } from "../../components/careers/PublicAuthLayout";
import { useT } from "../../i18n";
import { Emoji } from "../../ui-kit";

interface Check {
  genuine: boolean; valid: boolean; company: string; title?: string; issued_to?: string | null; employee_code?: string | null;
  issued_on?: string | null; reference?: string | null; version?: number; signed?: boolean | null; note?: string | null;
}

// Part 22.6: what the QR code on a letter opens. Public -- a bank or a future employer checks the letter is genuine.
export default function VerifyLetterPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { token = "" } = useParams<{ token: string }>();
  const [check, setCheck] = useState<Check | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    http.get<Check>(`/api/v1/public/core-hr/letters/check/${encodeURIComponent(token)}`).then(setCheck).catch(() => setFailed(true));
  }, [token]);

  const ok = check?.genuine && check.valid;
  const day = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" }) : "-");
  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default", px: 2, py: 5 }}>
      <Box sx={{ maxWidth: 560, mx: "auto" }}>
        <Stack direction="row" justifyContent="flex-end" sx={{ mb: 1 }}><LanguagePicker /></Stack>
        <Card sx={{ p: 3.5, textAlign: "center" }}>
          {!check && !failed ? <CircularProgress /> : (
            <>
              <Emoji name={ok ? "check" : check?.genuine ? "warning" : "cross"} size={56} />
              <Typography variant="h5" sx={{ fontWeight: 800, mt: 1.5, color: ok ? f.ok : check?.genuine ? f.sunInk : f.coral }} data-testid="verify-result">
                {ok ? t("verify22.genuine") : check?.genuine ? t("verify22.not_current") : t("verify22.not_found")}
              </Typography>
              {check?.company && <Typography sx={{ color: f.muted, mt: 0.5 }}>{t("verify22.issued_by", { company: check.company })}</Typography>}
              {check?.genuine && (
                <Box component="dl" sx={{ textAlign: "left", display: "grid", gridTemplateColumns: "auto 1fr", gap: "8px 16px", mt: 3, mx: "auto", maxWidth: 400 }}>
                  {([
                    ["verify22.letter", check.title],
                    ["verify22.issued_to", check.issued_to ? `${check.issued_to}${check.employee_code ? ` (${check.employee_code})` : ""}` : null],
                    ["verify22.date", day(check.issued_on)],
                    ["verify22.reference", check.reference],
                    ["verify22.version", check.version ? String(check.version) : null],
                  ] as [string, string | null | undefined][]).filter(([, v]) => v).map(([k, v]) => (
                    <Box key={k} sx={{ display: "contents" }}>
                      <Typography component="dt" sx={{ color: f.muted }}>{t(k)}</Typography>
                      <Typography component="dd" sx={{ m: 0, fontWeight: 700 }}>{v}</Typography>
                    </Box>
                  ))}
                </Box>
              )}
              {check?.note && <Typography sx={{ mt: 2, color: f.sunInk }}>{check.note}</Typography>}
              <Typography sx={{ mt: 3, fontSize: 12, color: f.muted }}>{t("verify22.privacy")}</Typography>
            </>
          )}
        </Card>
      </Box>
    </Box>
  );
}
