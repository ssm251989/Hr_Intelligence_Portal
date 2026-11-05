import Box from "@mui/material/Box";
import Container from "@mui/material/Container";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink, Outlet } from "react-router-dom";

import { useBootstrap } from "../bootstrap/BootstrapContext";
import { BrandMark, LanguagePicker } from "../components/careers/PublicAuthLayout";
import { useT } from "../i18n";

// Public career site shell (no staff login): company name, mark and colours all come from
// the public branding; footer shows the company's own contact + legal links if set.
export default function CareersLayout() {
  const f = useTheme().palette.fresh;
  const t = useT();
  const { productName, branding } = useBootstrap();
  const links = branding?.legal_links ?? [];

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", flexDirection: "column", bgcolor: f.ground }}>
      <Box component="header" sx={{ bgcolor: f.surface, boxShadow: f.shadow }}>
        <Container maxWidth="lg" sx={{ py: 1.75 }}>
          <Stack direction="row" alignItems="center" spacing={2} justifyContent="space-between">
            <Box component={RouterLink} to="/careers" aria-label={t("careers.site_title", { name: productName })} sx={{ textDecoration: "none", color: "inherit", minWidth: 0, borderRadius: "12px", "&:focus-visible": { outline: `2px solid ${f.brand}`, outlineOffset: 2 } }}>
              <Stack direction="row" spacing={1} alignItems="baseline" sx={{ minWidth: 0 }}>
                <BrandMark size={36} />
                <Typography component="span" sx={{ color: f.muted, fontWeight: 600, display: { xs: "none", sm: "inline" } }}>{t("careers.careers_word")}</Typography>
              </Stack>
            </Box>
            <LanguagePicker />
          </Stack>
        </Container>
      </Box>

      <Container component="main" maxWidth="lg" sx={{ py: { xs: 3, md: 5 }, flex: 1 }}>
        <Outlet />
      </Container>

      <Box component="footer" sx={{ borderTop: `1px solid ${f.line}`, py: 3, bgcolor: f.surface }}>
        <Container maxWidth="lg">
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems="center" justifyContent="space-between">
            <Typography variant="body2" sx={{ color: f.muted }}>
              {t("careers.footer_rights", { year: String(new Date().getFullYear()), name: productName })}
            </Typography>
            <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 0.5, fontSize: 13, color: f.muted }}>
              {branding?.support_contact && (
                <Box component="a" href={`mailto:${branding.support_contact}`} sx={{ color: "inherit" }}>{branding.support_contact}</Box>
              )}
              {links.map((l) => (
                <Box key={l} component="a" href={l} target="_blank" rel="noopener noreferrer" sx={{ color: "inherit" }}>{l.replace(/^https?:\/\//, "")}</Box>
              ))}
            </Stack>
          </Stack>
        </Container>
      </Box>
    </Box>
  );
}
