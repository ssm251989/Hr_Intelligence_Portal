import { http, intelligenceApi } from "./client";

// Part 15.4 Reports (R4): downloads for saved reports. The export endpoint needs the
// signed-in user's token, so the file is fetched as a blob (not a plain link).
export type SavedReportFormat = "csv" | "xlsx";

export const reportsExtraApi = {
  savedReports: () => intelligenceApi.reports(),
  exportSavedReport: (reportId: string, format: SavedReportFormat) => http.fetchBlob(intelligenceApi.exportUrl(reportId, format)),
};
