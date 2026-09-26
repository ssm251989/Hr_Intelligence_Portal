// Part 15.4 Reports (R4): client-side CSV for the fixed reports (their data is already on
// screen) and "Save as PDF" through the browser's own print dialog (no PDF renderer on the
// server yet -- see backend app/analytics/report_builder.py export()).

type Cell = string | number | null | undefined;

function csvCell(value: Cell): string {
  const text = value == null ? "" : String(value);
  // Neutralise spreadsheet formulas (CSV injection) and quote when needed.
  const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadCsv(filename: string, header: string[], rows: Cell[][]): void {
  const lines = [header, ...rows].map((r) => r.map(csvCell).join(","));
  // BOM so Excel opens UTF-8 (Hindi/Tamil text) correctly.
  saveBlob(new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" }), filename.endsWith(".csv") ? filename : `${filename}.csv`);
}

export function printReport(): void {
  window.print();
}

export function fileSlug(text: string): string {
  return text.trim().toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "") || "report";
}
