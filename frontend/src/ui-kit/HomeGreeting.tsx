import { useEffect, useState, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { experienceApi } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useT } from "../i18n";
import Emoji from "./Emoji";
import Illustration from "./Illustration";

// Part 15 C: "Good morning/afternoon/evening, <first name> 👋" + "N things need you today".
// N = everything waiting on this user in the unified inbox (approvals, feedback, tasks...).

export function timeOfDay(date = new Date()): "morning" | "afternoon" | "evening" {
  const h = date.getHours();
  return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
}

export function firstName(fullName: string | null | undefined, email?: string): string {
  const name = (fullName ?? "").trim().split(/\s+/)[0];
  if (name) return name;
  const local = (email ?? "").split("@")[0].split(/[._-]/)[0];
  return local ? local[0].toUpperCase() + local.slice(1) : "";
}

export default function HomeGreeting({ extra }: { extra?: ReactNode }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { user } = useAuth();
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    experienceApi.inbox().then((items) => setCount(items.length)).catch(() => setCount(null));
  }, []);

  const name = firstName(user?.full_name, user?.email);
  const hello = t(`greeting.${timeOfDay()}`, { name }).replace(/,\s*$/, "");

  return (
    <Card sx={{ p: { xs: 2.5, md: 3.5 }, mb: 2.5, background: `linear-gradient(120deg, ${f.brandSoft} 0%, ${f.surface} 62%)`, overflow: "hidden" }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={3} alignItems="center">
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="h1" component="h1" sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }} data-tour="page-title">
            {hello} <Emoji name="waving_hand" size={30} />
          </Typography>
          <Typography sx={{ color: f.muted, mt: 0.75, fontSize: 16 }}>
            {count === null ? " " : count > 0 ? t("greeting.things_today", { count }) : t("greeting.nothing_today")}
          </Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: "wrap", rowGap: 1 }}>
            {count !== null && count > 0 && (
              <Box data-tour="page-primary" sx={{ display: "inline-flex" }}>
                <Button variant="contained" component={RouterLink} to="/approvals" startIcon={<Emoji name="check" size={16} />}>
                  {t("greeting.see_all")}
                </Button>
              </Box>
            )}
            {extra}
          </Stack>
        </Box>
        <Illustration name="hello" height={150} sx={{ display: { xs: "none", sm: "block" }, maxWidth: 240 }} />
      </Stack>
    </Card>
  );
}
