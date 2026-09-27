import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { useBootstrap } from "../../bootstrap/BootstrapContext";
import { LOCALES, useI18n } from "../../i18n";
import { Illustration, type IllustrationName } from "../../ui-kit";

export function BrandMark({ size = 40 }: { size?: number }) {
  const f = useTheme().palette.fresh;
  const { productName, logoMark, logoUrl } = useBootstrap();
  return (
    <Stack direction="row" spacing={1.25} alignItems="center" sx={{ minWidth: 0 }}>
      {logoUrl ? (
        <Box component="img" src={logoUrl} alt="" sx={{ height: size, maxWidth: size * 3, objectFit: "contain", flexShrink: 0 }} />
      ) : (
        <Box aria-hidden sx={{ width: size, height: size, borderRadius: "12px", bgcolor: f.brand, color: f.brandInk, display: "grid", placeItems: "center", fontWeight: 800, fontSize: size * 0.36, flexShrink: 0 }}>
          {logoMark}
        </Box>
      )}
      <Typography sx={{ fontWeight: 800, fontSize: size * 0.42, minWidth: 0 }} noWrap title={productName}>
        {productName}
      </Typography>
    </Stack>
  );
}

export function LanguagePicker() {
  const { locale, setLocale, t } = useI18n();
  return (
    <TextField select size="small" value={locale} onChange={(e) => setLocale(e.target.value)} label={t("login.language")} sx={{ minWidth: 130 }}>
      {LOCALES.map((l) => (
        <MenuItem key={l.code} value={l.code}>{l.label}</MenuItem>
      ))}
    </TextField>
  );
}

// Part 15.4 (B1): the friendly split layout for sign-in / register / set password --
// company name + mark and colours come from the public branding, the drawing from the kit.
export default function PublicAuthLayout({ illustration, headline, tagline, children }: { illustration: IllustrationName; headline: ReactNode; tagline: ReactNode; children: ReactNode }) {
  const f = useTheme().palette.fresh;
  const { branding } = useBootstrap();
  const links = branding?.legal_links ?? [];
  return (
    <Box sx={{ minHeight: "100vh", bgcolor: f.ground, display: "grid", gridTemplateColumns: { xs: "1fr", md: "minmax(0, 1.1fr) minmax(0, 1fr)" } }}>
      <Box
        component="section"
        aria-hidden={false}
        sx={{
          display: { xs: "none", md: "flex" }, flexDirection: "column", justifyContent: "space-between", p: 5, gap: 4,
          background: `linear-gradient(135deg, ${f.brandSoft}, ${f.surface} 60%, ${f.skySoft})`,
        }}
      >
        <BrandMark />
        <Box>
          <Illustration name={illustration} height={300} sx={{ mx: "auto" }} />
          <Typography component="p" sx={{ fontWeight: 800, fontSize: 28, lineHeight: 1.2, mt: 4, maxWidth: "22ch", textWrap: "balance" }}>{headline}</Typography>
          <Typography sx={{ color: f.muted, mt: 1.5, maxWidth: "46ch" }}>{tagline}</Typography>
        </Box>
        <Box />
      </Box>

      <Box component="main" sx={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", px: 2, py: 4, gap: 3 }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ width: "100%", maxWidth: 440 }}>
          <Box sx={{ display: { xs: "block", md: "none" }, minWidth: 0 }}>
            <BrandMark size={34} />
          </Box>
          <Box sx={{ ml: "auto" }}>
            <LanguagePicker />
          </Box>
        </Stack>
        <Card sx={{ width: "100%", maxWidth: 440, p: { xs: 3, sm: 4 } }}>{children}</Card>
        {(branding?.support_contact || links.length > 0) && (
          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 0.5, justifyContent: "center", fontSize: 13, color: f.muted }}>
            {branding?.support_contact && (
              <Box component="a" href={`mailto:${branding.support_contact}`} sx={{ color: "inherit" }}>{branding.support_contact}</Box>
            )}
            {links.map((l) => (
              <Box key={l} component="a" href={l} target="_blank" rel="noopener noreferrer" sx={{ color: "inherit" }}>
                {l.replace(/^https?:\/\//, "")}
              </Box>
            ))}
          </Stack>
        )}
      </Box>
    </Box>
  );
}
