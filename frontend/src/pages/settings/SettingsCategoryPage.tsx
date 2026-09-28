import { useMemo, useState } from "react";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Collapse from "@mui/material/Collapse";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink, Navigate, NavLink, useNavigate, useParams } from "react-router-dom";

import { useT } from "../../i18n";
import { visibleCategories } from "../../settings/catalog";
import { EmptyState, Emoji, PageHeader } from "../../ui-kit";
import { useSettingsPerms } from "./SettingsHomePage";

// Part 16.3: one Settings category = a left sub-menu of its pages (rare ones under "Advanced")
// + the chosen page on the right.

export default function SettingsCategoryPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const navigate = useNavigate();
  const { category = "", page } = useParams();
  const perms = useSettingsPerms();
  const cats = useMemo(() => visibleCategories(perms), [perms.admin, perms.mailbox]); // eslint-disable-line react-hooks/exhaustive-deps
  const cat = cats.find((c) => c.id === category);
  const current = cat?.pages.find((p) => p.id === page);
  const [advancedOpen, setAdvancedOpen] = useState(Boolean(current?.advanced));

  if (!cat) {
    return <EmptyState illustration="access-denied" title={t("settingsHome.not_found")} action={<Button variant="contained" component={RouterLink} to="/settings">{t("settingsHome.back")}</Button>} />;
  }
  if (!current) return <Navigate to={`/settings/${cat.id}/${cat.pages[0].id}`} replace />;

  const main = cat.pages.filter((p) => !p.advanced);
  const advanced = cat.pages.filter((p) => p.advanced);
  const go = (path: string) => navigate(`/settings/${path}`);

  const link = (p: (typeof cat.pages)[number]) => (
    <Box key={p.id} component={NavLink} to={`/settings/${cat.id}/${p.id}`}
      sx={{
        display: "flex", alignItems: "center", gap: 1.25, px: 1.25, py: 1, borderRadius: "10px", textDecoration: "none", fontSize: 14,
        color: f.ink, fontWeight: 500, "&.active": { bgcolor: f.brandSoft, color: f.brand, fontWeight: 700 }, "&:hover": { bgcolor: f.surface2 },
        "&:focus-visible": { outline: `2px solid ${f.brand}` },
      }}>
      <Emoji name={p.emoji} size={18} />
      {t(`settingsHome.page.${cat.id}.${p.id}`)}
    </Box>
  );

  return (
    <Box>
      <PageHeader emoji={cat.emoji} title={t(`settingsHome.cat.${cat.id}`)} purpose={t(`settingsHome.cat.${cat.id}.hint`)} tourKey="settings"
        extra={<Button component={RouterLink} to="/settings" startIcon={<ArrowBackIcon />}>{t("settingsHome.all_settings")}</Button>} />
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "250px minmax(0, 1fr)" }, gap: 2.5, alignItems: "start" }}>
        <Card component="nav" aria-label={t(`settingsHome.cat.${cat.id}`)} sx={{ p: 1.25, position: { md: "sticky" }, top: { md: 16 } }}>
          <Stack spacing={0.25}>
            {main.map(link)}
            {advanced.length > 0 && (
              <>
                <Box component="button" type="button" onClick={() => setAdvancedOpen((o) => !o)} aria-expanded={advancedOpen}
                  sx={{ display: "flex", alignItems: "center", gap: 1, px: 1.25, py: 1, mt: 0.5, border: 0, bgcolor: "transparent", font: "inherit", fontSize: 12,
                    fontWeight: 800, color: f.muted, cursor: "pointer", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  {t("comms.advanced")} {advancedOpen ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                </Box>
                <Collapse in={advancedOpen}><Stack spacing={0.25}>{advanced.map(link)}</Stack></Collapse>
              </>
            )}
          </Stack>
        </Card>
        <Box sx={{ minWidth: 0 }}>
          <Typography component="h2" sx={{ fontWeight: 800, fontSize: 20, mb: 1.5 }}>{t(`settingsHome.page.${cat.id}.${current.id}`)}</Typography>
          <Stack key={`${cat.id}/${current.id}`} spacing={2.5}>{current.render(go)}</Stack>
        </Box>
      </Box>
    </Box>
  );
}
