import { useState } from "react";
import Button from "@mui/material/Button";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";

import { useT } from "../i18n";

/** B1 (Part 27): a candidate form link HR can always share by WhatsApp / phone, emailed or not. */
export default function CopyLinkButton({ link, size = "small" }: { link: string | null | undefined; size?: "small" | "medium" }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  if (!link) return null;
  return (
    <Button size={size} startIcon={<ContentCopyIcon fontSize="small" />}
      onClick={() => { void navigator.clipboard.writeText(link).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2500); }); }}>
      {copied ? t("docrev.copied") : t("docrev.copy_link")}
    </Button>
  );
}
