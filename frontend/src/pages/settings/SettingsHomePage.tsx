import { useEffect, useMemo, useState } from "react";
import SearchIcon from "@mui/icons-material/Search";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import InputAdornment from "@mui/material/InputAdornment";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink, Navigate, useLocation } from "react-router-dom";

import { platformSettingsApi, type SettingDefinition } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { ROLE_MATRIX } from "../../auth/roles";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { useT } from "../../i18n";
import { LEGACY, pageForSetting, visibleCategories } from "../../settings/catalog";
import { Emoji, PageHeader } from "../../ui-kit";

// Part 16.3: Settings home = a grid of category cards + one search box that finds any page
// or any single setting by its friendly name.

function norm(s: string): string {
  return s.toLocaleLowerCase().normalize("NFKD").replace(/\p{M}/gu, "");
}

export function useSettingsPerms() {
  const { can } = useAuth();
  const { data } = useMeBootstrap();
  return { admin: can(ROLE_MATRIX.platformSettingsWrite), mailbox: can(ROLE_MATRIX.hrIntegrationWrite), twoStep: Boolean(data?.two_step) };
}

export default function SettingsHomePage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const location = useLocation();
  const perms = useSettingsPerms();
  const cats = useMemo(() => visibleCategories(perms), [perms.admin, perms.mailbox]); // eslint-disable-line react-hooks/exhaustive-deps
  const [q, setQ] = useState("");
  const [defs, setDefs] = useState<SettingDefinition[]>([]);

  useEffect(() => {
    if (perms.admin) platformSettingsApi.definitions().then(setDefs).catch(() => undefined);
  }, [perms.admin]);

  // Older links (/settings#connections, error "fix" buttons) land on the new page.
  const hash = decodeURIComponent(location.hash.replace(/^#/, "")).toLowerCase();
  if (hash && LEGACY[hash]) return <Navigate to={`/settings/${LEGACY[hash]}`} replace />;

  const needle = norm(q.trim());
  const pageHits = needle
    ? cats.flatMap((c) => c.pages.map((p) => ({ c, p, text: norm(`${t(`settingsHome.cat.${c.id}`)} ${t(`settingsHome.page.${c.id}.${p.id}`)} ${p.keywords ?? ""}`) })))
        .filter((h) => h.text.includes(needle)).slice(0, 12)
    : [];
  const settingHits = needle.length >= 3
    ? defs.filter((d) => norm(`${d.help ?? ""} ${d.affects ?? ""}`).includes(needle)).slice(0, 10)
    : [];

  return (
    <Box>
      <PageHeader emoji="gear" title={t("settingsPage.title")} purpose={t("settingsHome.purpose")} tourKey="settings"
        below={
          <TextField value={q} onChange={(e) => setQ(e.target.value)} fullWidth placeholder={t("settingsHome.search_example")}
            slotProps={{ htmlInput: { "aria-label": t("settingsPage.search_label") }, input: { startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> } }}
            sx={{ maxWidth: 640 }} />
        } />

      {needle ? (
        <Stack spacing={2}>
          {pageHits.length === 0 && settingHits.length === 0 && (
            <Typography sx={{ color: f.muted }}>{t("settingsHome.search_none")}</Typography>
          )}
          {pageHits.length > 0 && (
            <Card sx={{ p: 1 }}>
              {pageHits.map(({ c, p }) => (
                <CardActionArea key={`${c.id}/${p.id}`} component={RouterLink} to={`/settings/${c.id}/${p.id}`} sx={{ p: 1.5, borderRadius: "12px" }}>
                  <Stack direction="row" spacing={1.5} alignItems="center">
                    <Emoji name={p.emoji} size={20} />
                    <Typography sx={{ fontWeight: 700 }}>{t(`settingsHome.page.${c.id}.${p.id}`)}</Typography>
                    <Typography sx={{ color: f.muted, fontSize: 13 }}>{t(`settingsHome.cat.${c.id}`)}</Typography>
                  </Stack>
                </CardActionArea>
              ))}
            </Card>
          )}
          {settingHits.length > 0 && (
            <Card sx={{ p: 1 }}>
              <Typography sx={{ px: 1.5, pt: 1, fontWeight: 800, fontSize: 13, color: f.muted }}>{t("settingsHome.search_settings")}</Typography>
              {settingHits.map((d) => (
                <CardActionArea key={d.key} component={RouterLink} to={`/settings/${pageForSetting(d.key, cats)}?q=${encodeURIComponent(q.trim())}`} sx={{ p: 1.5, borderRadius: "12px" }}>
                  <Typography sx={{ fontWeight: 600 }}>{d.help}</Typography>
                  {d.affects && <Typography sx={{ color: f.muted, fontSize: 13 }}>{d.affects}</Typography>}
                </CardActionArea>
              ))}
            </Card>
          )}
        </Stack>
      ) : (
        <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)", lg: "repeat(3, 1fr)", xl: "repeat(4, 1fr)" } }}>
          {cats.map((c) => (
            <Card key={c.id}>
              <CardActionArea component={RouterLink} to={`/settings/${c.id}/${c.pages[0].id}`} sx={{ p: 2.5, height: "100%", display: "flex", alignItems: "flex-start", justifyContent: "flex-start" }}>
                <Stack direction="row" spacing={2} alignItems="flex-start">
                  <Box sx={{ width: 46, height: 46, borderRadius: "14px", bgcolor: f.brandSoft, display: "grid", placeItems: "center", flexShrink: 0 }}>
                    <Emoji name={c.emoji} size={24} />
                  </Box>
                  <Box>
                    <Typography sx={{ fontWeight: 800, fontSize: 16 }}>{t(`settingsHome.cat.${c.id}`)}</Typography>
                    <Typography sx={{ color: f.muted, fontSize: 13.5, mt: 0.25 }}>{t(`settingsHome.cat.${c.id}.hint`)}</Typography>
                  </Box>
                </Stack>
              </CardActionArea>
            </Card>
          ))}
        </Box>
      )}
    </Box>
  );
}
