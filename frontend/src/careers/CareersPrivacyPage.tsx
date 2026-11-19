import { useEffect, useState } from "react";
import Card from "@mui/material/Card";
import Typography from "@mui/material/Typography";

import { http } from "../api/client";
import { useT } from "../i18n";

// C2 (Part 27): the company's privacy notice for applicants (published under Settings > Privacy), linked from
// the consent line on the apply form. No notice published yet -> say so plainly, never invent one.
export default function CareersPrivacyPage() {
  const t = useT();
  const [notice, setNotice] = useState<{ title: string | null; body: string | null } | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    http.get<{ title: string | null; body: string | null }>("/api/v1/public/privacy/notice/recruitment.application")
      .then(setNotice).catch(() => setFailed(true));
  }, []);
  return (
    <Card sx={{ p: { xs: 2.5, sm: 4 }, maxWidth: 760 }}>
      <Typography variant="h1" component="h1" sx={{ fontSize: 26, mb: 2 }}>{notice?.title || t("careers.privacy.title")}</Typography>
      {notice?.body ? <Typography sx={{ whiteSpace: "pre-wrap" }}>{notice.body}</Typography>
        : (notice || failed) && <Typography sx={{ color: "text.secondary" }}>{t("careers.privacy.none")}</Typography>}
    </Card>
  );
}
