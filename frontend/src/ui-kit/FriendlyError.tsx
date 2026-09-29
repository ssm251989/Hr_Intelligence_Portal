import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { ApiError } from "../api/client";
import { t as tr, useT } from "../i18n";
import Illustration from "./Illustration";

// Part 15 C: every error says WHAT happened + HOW to fix it + a button to the right page.
// Pass either explicit text or the caught error (API errors are translated to plain words).

interface Explained {
  what: string;
  fix: string;
  actionLabel?: string;
  actionTo?: string;
}

export function explainError(err: unknown): Explained {
  if (err instanceof ApiError) {
    // Part 14 section 8 envelope: {code, message, fix, fix_path} -- the server already knows
    // the plain-language fix and which settings page repairs it.
    const body = typeof err.detail === "object" && err.detail !== null ? (err.detail as { message?: string; fix?: string; fix_path?: string; fix_label?: string }) : null;
    const detail = typeof err.detail === "string" ? err.detail : body?.message;
    if (body?.fix) return { what: detail || tr("error.failed"), fix: body.fix, actionLabel: body.fix_path ? (body.fix_label ?? tr("error.open_settings")) : undefined, actionTo: body.fix_path };
    if (err.status === 401) return { what: tr("error.signed_out"), fix: tr("error.signed_out_fix"), actionLabel: tr("action.sign_in"), actionTo: "/login" };
    if (err.status === 403) return { what: tr("error.no_access"), fix: tr("error.no_access_fix"), actionLabel: tr("action.go_home"), actionTo: "/" };
    if (err.status === 404) return { what: detail || tr("error.not_found"), fix: tr("error.not_found_fix"), actionLabel: tr("action.go_home"), actionTo: "/" };
    if (err.status === 429) return { what: tr("error.too_many"), fix: tr("error.too_many_fix") };
    if (err.status >= 500) return { what: tr("error.server"), fix: tr("error.server_fix") };
    return { what: detail || tr("error.failed"), fix: tr("error.failed_fix") };
  }
  if (err instanceof TypeError) return { what: tr("error.offline"), fix: tr("error.offline_fix") };
  return { what: tr("error.generic"), fix: tr("error.generic_fix") };
}

export default function FriendlyError({
  error, what, fix, actionLabel, actionTo, onRetry, compact,
}: {
  error?: unknown;
  what?: string;
  fix?: string;
  actionLabel?: string;
  actionTo?: string;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const t = useTheme().palette.fresh;
  const tt = useT();
  const e = error !== undefined ? explainError(error) : null;
  const text = { what: what ?? e?.what ?? tt("error.generic"), fix: fix ?? e?.fix ?? tt("error.generic_fix"), actionLabel: actionLabel ?? e?.actionLabel, actionTo: actionTo ?? e?.actionTo };
  return (
    <Card role="alert" sx={{ p: compact ? 2 : 3, bgcolor: t.coralSoft, boxShadow: "none" }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2.5} alignItems="center">
        {!compact && <Illustration name="server-down" height={110} tone="coral" sx={{ maxWidth: 170 }} />}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontWeight: 800, fontSize: 16 }}>{text.what}</Typography>
          <Typography sx={{ color: t.ink, opacity: 0.8, mt: 0.5 }}>{text.fix}</Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
            {onRetry && <Button variant="contained" onClick={onRetry}>{tt("action.retry")}</Button>}
            {text.actionLabel && text.actionTo && (
              <Button variant={onRetry ? "outlined" : "contained"} component={RouterLink} to={text.actionTo}>{text.actionLabel}</Button>
            )}
          </Stack>
        </Box>
      </Stack>
    </Card>
  );
}
