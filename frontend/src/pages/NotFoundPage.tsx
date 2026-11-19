import { Link as RouterLink } from "react-router-dom";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";

import { useT } from "../i18n";
import { EmptyState } from "../ui-kit";

// X2 (Part 27): an unknown address inside the app shows this (with the menu) instead of a blank page.
export default function NotFoundPage() {
  const t = useT();
  return (
    <Card>
      <EmptyState illustration="page-not-found" title={t("notfound.title")} hint={t("notfound.hint")}
        action={<Button component={RouterLink} to="/" variant="contained">{t("notfound.home")}</Button>} />
    </Card>
  );
}
