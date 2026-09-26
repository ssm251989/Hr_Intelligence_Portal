import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { useT } from "../i18n";
import { Emoji, FriendlyAnimation } from "../ui-kit";

export default function CareersThankYouPage() {
  const f = useTheme().palette.fresh;
  const t = useT();
  const steps = [
    { emoji: "inbox", text: t("careers.thanks.step_received") },
    { emoji: "eyes", text: t("careers.thanks.step_review") },
    { emoji: "mail", text: t("careers.thanks.step_email") },
  ];
  return (
    <Card sx={{ maxWidth: 640, mx: "auto", p: { xs: 3, sm: 5 }, textAlign: "center" }} role="status">
      <Box sx={{ display: "grid", placeItems: "center" }}>
        <FriendlyAnimation name="success" size={110} />
      </Box>
      <Typography variant="h1" component="h1" sx={{ fontSize: 28, mt: 1 }}>{t("careers.thanks.title")}</Typography>
      <Typography sx={{ color: f.muted, mt: 1, mb: 3 }}>{t("careers.thanks.body")}</Typography>
      <Stack spacing={1} sx={{ textAlign: "left", mb: 3 }}>
        {steps.map((s, i) => (
          <Stack key={s.emoji} direction="row" spacing={1.5} alignItems="center" sx={{ p: 1.25, borderRadius: "12px", bgcolor: i === 0 ? f.okSoft : f.surface2, border: `1px solid ${i === 0 ? "transparent" : f.line}` }}>
            <Emoji name={s.emoji} size={22} />
            <Typography sx={{ fontWeight: i === 0 ? 700 : 500 }}>{s.text}</Typography>
          </Stack>
        ))}
      </Stack>
      <Button component={RouterLink} to="/careers" variant="contained">
        {t("careers.thanks.more")}
      </Button>
    </Card>
  );
}
