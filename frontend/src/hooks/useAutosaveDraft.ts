import { useEffect, useRef, useState } from "react";

import { experienceApi } from "../api/client";

// Part 14 section 6 / L-F3 (docs/HRMS_COMPLETE_SPEC.txt): autosave drafts for long forms.
// Server-side (so a draft follows the user across devices), debounced, and restorable:
//   const { restored, savedAt, clear } = useAutosaveDraft("performance.review", review.id, formValues, setFormValues);

export function useAutosaveDraft<T extends Record<string, unknown>>(
  formKey: string,
  entityRef: string,
  value: T,
  onRestore: (draft: T) => void,
  delayMs = 1500,
) {
  const [restored, setRestored] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const loaded = useRef(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    loaded.current = false;
    experienceApi
      .getDraft(formKey, entityRef)
      .then((r) => {
        if (r.data) {
          onRestore(r.data as T);
          setRestored(true);
          setSavedAt(r.updated_at);
        }
      })
      .catch(() => undefined)
      .finally(() => {
        loaded.current = true;
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formKey, entityRef]);

  useEffect(() => {
    if (!loaded.current) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      experienceApi.saveDraft(formKey, value, entityRef).then((r) => setSavedAt(r.updated_at)).catch(() => undefined);
    }, delayMs);
    return () => window.clearTimeout(timer.current);
  }, [formKey, entityRef, value, delayMs]);

  const clear = () => experienceApi.discardDraft(formKey, entityRef).then(() => setSavedAt(null));
  return { restored, savedAt, clear };
}
