// Part 32: the request for CTD Techs and the box for CTD's signed approval code - on the waiting page, on
// Settings > Licence and on "Choose what you want". The request travels by the company's own mailbox, or by the person:
// "Email CTD" opens their email program filled in; "Copy request" for anything else (chat, another PC...).
import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { useT } from "../../i18n";

export default function CtdRequestBox({ requestText, mailto, approver, busy, locked, onCode }: {
  requestText?: string | null; mailto?: string | null; approver?: string | null; busy?: boolean; locked?: string | null;
  onCode: (code: string) => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [code, setCode] = useState("");
  const [copied, setCopied] = useState(false);
  const clean = code.replace(/\s+/g, "");
  const looksRight = clean.startsWith("CTD1.") && clean.length > 40;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(requestText ?? "");
      setCopied(true);
    } catch {
      /* the text stays selectable */
    }
  };

  return (
    <Stack spacing={1.5}>
      {requestText && (
        <Box>
          <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
            {approver ? t("lic.send_to", { email: approver }) : t("lic.send_request")}
          </Typography>
          <Box component="pre" sx={{ m: 0, p: 1.25, maxHeight: 120, overflow: "auto", whiteSpace: "pre-wrap", wordBreak: "break-all", fontSize: 12,
            fontFamily: "monospace", bgcolor: f.surface, border: `1px solid ${f.line}`, borderRadius: "10px" }} aria-label={t("lic.request_text")}>
            {requestText}
          </Box>
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} useFlexGap flexWrap="wrap">
            {mailto && <Button variant="outlined" href={mailto}>{t("lic.email_ctd")}</Button>}
            <Button variant="outlined" onClick={() => void copy()}>{copied ? t("lic.copied") : t("lic.copy_request")}</Button>
          </Stack>
        </Box>
      )}
      <Stack component="form" spacing={1} onSubmit={(e) => { e.preventDefault(); if (looksRight) onCode(clean); }}>
        <TextField label={t("lic.code_label")} placeholder="CTD1...." value={code} onChange={(e) => setCode(e.target.value)} multiline minRows={2} maxRows={6}
          autoComplete="off" disabled={Boolean(locked)} sx={{ bgcolor: f.surface }} inputProps={{ "aria-label": t("lic.code_label"), style: { fontFamily: "monospace", fontSize: 13 } }}
          helperText={locked ? t("lic.locked_until", { time: new Date(locked).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) })
            : code && !looksRight ? t("lic.code_hint") : " "} />
        <Button type="submit" variant="contained" disabled={busy || !looksRight || Boolean(locked)} sx={{ alignSelf: "flex-start" }}>{t("lic.enter_code")}</Button>
      </Stack>
    </Stack>
  );
}
