import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { ApiError } from "../api/client";
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
    const detail = typeof err.detail === "string" ? err.detail : (err.detail as { message?: string } | null)?.message;
    if (err.status === 401) return { what: "You've been signed out.", fix: "Please sign in again to carry on.", actionLabel: "Sign in", actionTo: "/login" };
    if (err.status === 403) return { what: "You don't have access to this.", fix: "Ask your HR admin to give your role access.", actionLabel: "Go home", actionTo: "/" };
    if (err.status === 404) return { what: detail || "We couldn't find that.", fix: "It may have been moved or removed. Try going back to the list.", actionLabel: "Go home", actionTo: "/" };
    if (err.status >= 500) return { what: "Something went wrong on our side.", fix: "Please try again in a minute. If it keeps happening, tell your HR admin." };
    return { what: detail || "That didn't work.", fix: "Check the details and try again." };
  }
  if (err instanceof TypeError) return { what: "We couldn't reach the server.", fix: "Check your internet connection, then try again." };
  return { what: "Something went wrong.", fix: "Please try again." };
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
  const e = error !== undefined ? explainError(error) : null;
  const text = { what: what ?? e?.what ?? "Something went wrong.", fix: fix ?? e?.fix ?? "Please try again.", actionLabel: actionLabel ?? e?.actionLabel, actionTo: actionTo ?? e?.actionTo };
  return (
    <Card role="alert" sx={{ p: compact ? 2 : 3, bgcolor: t.coralSoft, boxShadow: "none" }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2.5} alignItems="center">
        {!compact && <Illustration name="server-down" height={110} tone="coral" sx={{ maxWidth: 170 }} />}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontWeight: 800, fontSize: 16 }}>{text.what}</Typography>
          <Typography sx={{ color: t.ink, opacity: 0.8, mt: 0.5 }}>{text.fix}</Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
            {onRetry && <Button variant="contained" onClick={onRetry}>Try again</Button>}
            {text.actionLabel && text.actionTo && (
              <Button variant={onRetry ? "outlined" : "contained"} component={RouterLink} to={text.actionTo}>{text.actionLabel}</Button>
            )}
          </Stack>
        </Box>
      </Stack>
    </Card>
  );
}
