import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useNavigate } from "react-router-dom";

import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { useT } from "../../i18n";
import { Emoji } from "../../ui-kit";

// Part 19.1: shown instead of a page whose module isn't active for the company (the menu
// already hides it; this covers a bookmark or a typed link). Admins get a button to the
// module picker; everyone else is told who can switch it on.
export default function ModuleNotActiveCard({ module }: { module: string }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const navigate = useNavigate();
  const { can } = useMeBootstrap();
  const isAdmin = can("platform.settings.configure");
  const key = `mod19.m.${module}.name`;
  const name = t(key) === key ? module : t(key);

  return (
    <Box sx={{ display: "grid", placeItems: "center", minHeight: "60vh", px: 2 }}>
      <Card sx={{ p: { xs: 3, sm: 4 }, maxWidth: 460, width: "100%", textAlign: "center" }}>
        <Box sx={{ width: 64, height: 64, borderRadius: "20px", bgcolor: f.brandSoft, display: "grid", placeItems: "center", mx: "auto", mb: 2 }}>
          <Emoji name="puzzle" size={36} />
        </Box>
        <Typography variant="h2" sx={{ fontSize: 22, mb: 1 }}>{t("mod19.not_active_title", { name })}</Typography>
        <Typography sx={{ color: f.muted, mb: 2.5 }}>{isAdmin ? t("mod19.not_active_admin") : t("mod19.not_active_user")}</Typography>
        {isAdmin && <Button variant="contained" size="large" onClick={() => navigate("/settings/company/modules")}>{t("mod19.open_modules")}</Button>}
      </Card>
    </Box>
  );
}
