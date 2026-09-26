import { useCallback, useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { ApiError } from "../../api/client";
import { reportsExtraApi, type SavedReportFormat } from "../../api/reportsExtra";
import { useT } from "../../i18n";
import { EmptyState, Emoji, FriendlyError } from "../../ui-kit";
import { fileSlug, saveBlob } from "./reportExport";

interface SavedReport {
  id: string;
  name: string;
  dataset: string;
}

// Part 15.4 Reports (R4): reports people saved from the builder, each downloadable as
// Excel or CSV (server-side export, same permission check as before). Hidden entirely for
// people who can't view saved reports.
export default function SavedReportsCard({ reloadKey }: { reloadKey: number }) {
  const f = useTheme().palette.fresh;
  const t = useT();
  const [rows, setRows] = useState<SavedReport[] | null>(null);
  const [hidden, setHidden] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [downloadFailed, setDownloadFailed] = useState(false);

  const load = useCallback(() => {
    setError(null);
    reportsExtraApi
      .savedReports()
      .then(setRows)
      .catch((err) => {
        if (err instanceof ApiError && (err.status === 403 || err.status === 404)) setHidden(true);
        else setError(err);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load, reloadKey]);

  const download = async (report: SavedReport, format: SavedReportFormat) => {
    setBusy(`${report.id}:${format}`);
    setDownloadFailed(false);
    try {
      const blob = await reportsExtraApi.exportSavedReport(report.id, format);
      if (!blob) {
        setDownloadFailed(true);
        return;
      }
      saveBlob(blob, `${fileSlug(report.name)}.${format}`);
    } finally {
      setBusy(null);
    }
  };

  if (hidden) return null;

  return (
    <Card sx={{ p: 2.5 }} data-print-hide>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
        <Emoji name="file_folder" size={20} />
        <Typography component="h2" sx={{ fontWeight: 700, fontSize: 16 }}>{t("reports.saved.title")}</Typography>
      </Stack>
      <Typography sx={{ color: f.muted, mb: 2 }}>{t("reports.saved.intro")}</Typography>
      {error ? (
        <FriendlyError error={error} onRetry={load} compact />
      ) : rows === null ? (
        <Typography sx={{ color: f.muted }}>{t("reports.loading")}</Typography>
      ) : rows.length === 0 ? (
        <EmptyState compact illustration="data-reports" title={t("reports.saved.empty")} hint={t("reports.saved.empty_hint")} />
      ) : (
        <Stack spacing={1}>
          {downloadFailed && <FriendlyError compact what={t("reports.saved.download_failed")} fix={t("reports.saved.download_failed_fix")} />}
          <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("reports.saved.count", { count: rows.length })}</Typography>
          {rows.map((r) => (
            <Box key={r.id} sx={{ display: "flex", flexWrap: "wrap", gap: 1, alignItems: "center", p: 1.25, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
              <Typography sx={{ fontWeight: 600, flex: "1 1 200px", minWidth: 0 }} noWrap title={r.name}>{r.name}</Typography>
              <Button size="small" variant="outlined" disabled={busy !== null} onClick={() => download(r, "xlsx")} aria-label={t("reports.saved.excel_aria", { name: r.name })}>
                {busy === `${r.id}:xlsx` ? t("reports.saved.downloading") : t("reports.export.excel")}
              </Button>
              <Button size="small" variant="outlined" disabled={busy !== null} onClick={() => download(r, "csv")} aria-label={t("reports.saved.csv_aria", { name: r.name })}>
                {busy === `${r.id}:csv` ? t("reports.saved.downloading") : t("reports.export.csv")}
              </Button>
            </Box>
          ))}
        </Stack>
      )}
    </Card>
  );
}
