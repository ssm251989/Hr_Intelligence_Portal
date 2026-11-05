import { candidatesApi } from "../api/client";
import type { UUID } from "../api/types";

/** Actually downloads a candidate's resume, rather than just linking to it.
 *
 * A locally-uploaded resume lives behind the same Bearer-token auth as every other API
 * call (see backend get_current_user, which only accepts an Authorization header) -- a
 * plain `<a href>`/window.open to that URL is a bare browser navigation carrying no such
 * header, so it 401s silently instead of downloading anything. This fetches the bytes
 * through the same authenticated request path as everything else (see
 * candidatesApi.fetchResumeBlob) and triggers a real browser download from the resulting
 * blob. An external http(s) link needs none of that -- it's just opened directly. */
export async function downloadResume(
  candidateId: UUID,
  resumePath: string | null | undefined,
  candidateName: string | null | undefined,
): Promise<void> {
  if (!resumePath) return;
  if (resumePath.startsWith("http://") || resumePath.startsWith("https://")) {
    window.open(resumePath, "_blank", "noreferrer");
    return;
  }

  const blob = await candidatesApi.fetchResumeBlob(candidateId);
  if (!blob) {
    throw new Error("Resume file could not be downloaded");
  }
  const extension = resumePath.includes(".") ? resumePath.slice(resumePath.lastIndexOf(".")) : "";
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = `${(candidateName || "resume").replace(/\s+/g, "_")}${extension}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}
