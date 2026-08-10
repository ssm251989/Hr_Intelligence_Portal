import { candidatesApi } from "../api/client";
import type { UUID } from "../api/types";

/** Where "Download/View Resume" should point for a candidate. CSV-imported candidates may
 * carry an external http(s) link instead of a locally uploaded file (see
 * backend/app/candidates/router.py import_candidates_csv, which never reads an arbitrary
 * server filesystem path) -- that case opens the link directly rather than hitting the
 * backend's file-download endpoint, which only serves real local uploads. */
export function resumeHref(candidateId: UUID, resumePath: string | null | undefined): string | null {
  if (!resumePath) return null;
  if (resumePath.startsWith("http://") || resumePath.startsWith("https://")) return resumePath;
  return candidatesApi.resumeDownloadUrl(candidateId);
}
