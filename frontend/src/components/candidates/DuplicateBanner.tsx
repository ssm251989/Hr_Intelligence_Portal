import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";

import { http } from "../../api/client";
import { useT } from "../../i18n";

interface Duplicate { candidate_id: string; name: string | null; email: string | null; reason: string }

const REASON_KEY: Record<string, string> = {
  "same email": "dup.reason.email",
  "same phone number": "dup.reason.phone",
  "same resume file": "dup.reason.file",
  "linked earlier record": "dup.reason.linked",
};

// Part 17.13/17.15: "This may be the same person as ..." on the candidate profile
// (GET /api/v1/ui/candidates/{id}/duplicates). Shows nothing when there is no match.
export default function DuplicateBanner({ candidateId }: { candidateId: string }) {
  const t = useT();
  const [dups, setDups] = useState<Duplicate[]>([]);

  useEffect(() => {
    let alive = true;
    http.get<{ duplicates: Duplicate[] }>(`/api/v1/ui/candidates/${candidateId}/duplicates`)
      .then((r) => { if (alive) setDups(r.duplicates); })
      .catch(() => { if (alive) setDups([]); });
    return () => { alive = false; };
  }, [candidateId]);

  if (dups.length === 0) return null;
  const d = dups[0];
  const key = REASON_KEY[d.reason];
  return (
    <Alert
      severity="warning"
      sx={{ mb: 2 }}
      action={<Button size="small" component={RouterLink} to={`/candidates?search=${encodeURIComponent(d.email || d.name || "")}`}>{t("dup.open")}</Button>}
    >
      {t("dup.banner", { name: d.name || d.email || t("bin.unnamed"), reason: key ? t(key) : d.reason })}
    </Alert>
  );
}
