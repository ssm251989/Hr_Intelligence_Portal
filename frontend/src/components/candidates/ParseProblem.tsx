import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import { Link as RouterLink } from "react-router-dom";

import { ApiError, extractErrorMessage } from "../../api/client";
import { useT } from "../../i18n";

export interface ParseProblemInfo {
  message: string;
  code?: string;
  fixUrl?: string;
}

/** The real reason a resume parse failed ({code, message, fix_url} from the API). */
export function parseProblemFrom(err: unknown, fallback: string): ParseProblemInfo {
  const detail = err instanceof ApiError ? err.detail : null;
  const d = detail && typeof detail === "object" && !Array.isArray(detail) ? (detail as { code?: string; fix_url?: string }) : {};
  return { message: extractErrorMessage(err, fallback), code: d.code, fixUrl: d.fix_url ?? undefined };
}

// Shown in the upload dialog and on the candidate page: the reason, where to fix it, and Retry.
export default function ParseProblem({ problem, onRetry, retrying }: { problem: ParseProblemInfo; onRetry?: () => void; retrying?: boolean }) {
  const t = useT();
  return (
    <Alert severity="warning">
      <strong>{t("candidates.parse.failed_title")}</strong> {problem.message}
      {(problem.fixUrl || onRetry) && (
        <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap", rowGap: 1 }}>
          {onRetry && (
            <Button size="small" variant="outlined" onClick={onRetry} disabled={retrying}>
              {retrying ? t("candidates.resume.parsing") : t("candidates.parse.retry")}
            </Button>
          )}
          {problem.fixUrl && (
            <Button size="small" component={RouterLink} to={problem.fixUrl}>
              {t("candidates.parse.fix")}
            </Button>
          )}
        </Stack>
      )}
    </Alert>
  );
}
