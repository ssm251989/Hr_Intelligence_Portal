import { useEffect, useState } from "react";

import { candidatesApi } from "../api/client";
import type { UUID } from "../api/types";

/** A candidate's extracted photo lives behind the same Bearer-token auth as every other
 * API call (see backend get_current_user) -- a plain <img>/<Avatar src> can't attach that
 * header itself, so the browser's native image load would silently 401 and just fall back
 * to the initials placeholder, defeating the feature entirely. This fetches the photo
 * through the same authenticated request path as everything else and hands back a local
 * blob URL for <Avatar src> to use instead of the raw (unauthenticated) download URL. */
export function useCandidatePhotoUrl(candidateId: UUID, photoPath: string | null | undefined): string | null {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!photoPath) {
      setBlobUrl(null);
      return;
    }
    let cancelled = false;
    let objectUrl: string | null = null;
    candidatesApi
      .fetchPhotoBlob(candidateId)
      .then((blob) => {
        if (cancelled || !blob) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setBlobUrl(null);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [candidateId, photoPath]);

  return blobUrl;
}
