import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { useBootstrap } from "../../bootstrap/BootstrapContext";
import { useT } from "../../i18n";
import { Emoji } from "../../ui-kit";

// Part 15.4 Settings: "Company & branding" -- a live look at what people see today (name,
// mark, colours from the company's theme) and where each part is changed. The editors
// themselves stay in their existing panels.
export default function BrandingGuideCard({ onOpen }: { onOpen: (categoryId: string) => void }) {
  const theme = useTheme();
  const f = theme.palette.fresh;
  const t = useT();
  const { productName, logoMark } = useBootstrap();
  const swatches: { key: string; colour: string }[] = [
    { key: "settingsPage.branding.swatch_main", colour: f.brand },
    { key: "settingsPage.branding.swatch_accent", colour: f.coral },
    { key: "settingsPage.branding.swatch_sun", colour: f.sun },
    { key: "settingsPage.branding.swatch_sky", colour: f.sky },
  ];
  const steps = [
    { emoji: "building", title: "settingsPage.branding.name_title", hint: "settingsPage.branding.name_hint", to: "all" },
    { emoji: "sparkles", title: "settingsPage.branding.colours_title", hint: "settingsPage.branding.colours_hint", to: "communications" },
    { emoji: "clapper", title: "settingsPage.branding.media_title", hint: "settingsPage.branding.media_hint", to: "media" },
  ];
  return (
    <Stack spacing={2}>
      <Card sx={{ p: 2.5, background: `linear-gradient(120deg, ${f.brandSoft}, ${f.surface} 70%)` }}>
        <Typography sx={{ color: f.muted, fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em", mb: 1.5 }}>
          {t("settingsPage.branding.preview")}
        </Typography>
        <Stack direction="row" spacing={1.5} alignItems="center">
          <Box sx={{ width: 48, height: 48, borderRadius: "14px", bgcolor: f.brand, color: f.brandInk, display: "grid", placeItems: "center", fontWeight: 800 }}>{logoMark}</Box>
          <Typography sx={{ fontWeight: 800, fontSize: 20 }}>{productName}</Typography>
        </Stack>
        <Stack direction="row" spacing={2} sx={{ mt: 2, flexWrap: "wrap", rowGap: 1 }}>
          {swatches.map((s) => (
            <Stack key={s.key} direction="row" spacing={0.75} alignItems="center">
              <Box aria-hidden sx={{ width: 18, height: 18, borderRadius: "6px", bgcolor: s.colour, border: `1px solid ${f.line}` }} />
              <Typography sx={{ fontSize: 13, color: f.muted }}>{t(s.key)}</Typography>
            </Stack>
          ))}
        </Stack>
      </Card>
      {steps.map((s) => (
        <Card key={s.title} sx={{ p: 2 }}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "flex-start", sm: "center" }}>
            <Emoji name={s.emoji} size={26} />
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography sx={{ fontWeight: 700 }}>{t(s.title)}</Typography>
              <Typography sx={{ color: f.muted, fontSize: 13 }}>{t(s.hint)}</Typography>
            </Box>
            <Button variant="outlined" size="small" onClick={() => onOpen(s.to)}>{t("settingsPage.branding.open")}</Button>
          </Stack>
        </Card>
      ))}
    </Stack>
  );
}
