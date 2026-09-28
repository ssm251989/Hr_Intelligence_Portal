import { useCallback, useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { automationApi, type HealthLight, type SystemHealth, type SystemHealthItem } from "../../api/automationApi";
import { useT } from "../../i18n";
import { Emoji, FriendlyError, StatusChip, type Tone } from "../../ui-kit";

// Part 17.13: Settings > Data & privacy > System health -- is everything this app depends on
// working? One traffic-light card per part (database, mailbox, AI, storage, background jobs),
// in plain words, with a link to the page that fixes it.

const EMOJI: Record<string, string> = { database: "package", mailbox: "mail", ai: "robot", storage: "file_folder", jobs: "gear" };
const FIX: Record<string, string> = {
  mailbox: "/settings/communication/mailboxes",
  ai: "/settings/integrations/ai",
  storage: "/settings/integrations/storage",
};
const TONE: Record<HealthLight, Tone> = { green: "ok", amber: "sun", red: "coral" };
const KNOWN = new Set(["database", "mailbox", "ai", "storage", "jobs"]);

const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—");

export default function SystemHealthPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [data, setData] = useState<SystemHealth | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<unknown>(null);

  const load = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    automationApi
      .systemHealth(true)
      .then(setData)
      .catch(setLoadError)
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const bg: Record<HealthLight, string> = { green: f.okSoft, amber: f.sunSoft, red: f.coralSoft };
  const dot: Record<HealthLight, string> = { green: f.ok, amber: f.sun, red: f.coral };

  const card = (item: SystemHealthItem, i: number) => {
    const known = KNOWN.has(item.key);
    const fix = item.status !== "green" ? FIX[item.key] : undefined;
    return (
      <Card key={`${item.key}-${i}`} sx={{ boxShadow: "none", border: `1px solid ${f.line}`, bgcolor: bg[item.status] ?? f.surface2 }}>
        <CardContent>
          <Stack direction="row" spacing={1.25} alignItems="center" sx={{ mb: 1 }}>
            <Box aria-hidden sx={{ width: 14, height: 14, borderRadius: "50%", bgcolor: dot[item.status] ?? f.muted, flexShrink: 0 }} />
            <Emoji name={EMOJI[item.key] ?? "tools"} size={20} />
            <Typography sx={{ fontWeight: 800, flex: 1 }}>{known ? t(`autom.sys.item.${item.key}`) : t("autom.sys.item.other")}</Typography>
            <StatusChip tone={TONE[item.status] ?? "muted"} label={t(`autom.sys.light.${item.status}`)} />
          </Stack>
          <Typography sx={{ fontSize: 14 }}>{item.message}</Typography>
          <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" sx={{ mt: 1.25 }} flexWrap="wrap" useFlexGap>
            <Typography variant="caption" sx={{ color: f.muted }}>{t("autom.sys.last_checked", { when: when(item.checked_at) })}</Typography>
            {fix && (
              <Button size="small" variant="outlined" component={RouterLink} to={fix}>{t(`autom.sys.fix.${item.key}`)}</Button>
            )}
          </Stack>
        </CardContent>
      </Card>
    );
  };

  return (
    <Card>
      <CardContent>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ mb: 0.5 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ flex: 1 }}>
            <Emoji name="check" size={22} />
            <Typography variant="h6">{t("autom.sys.title")}</Typography>
          </Stack>
          <Button variant="outlined" onClick={load} disabled={loading} startIcon={<Emoji name="magnifier" size={16} />}>
            {loading ? t("autom.sys.checking") : t("autom.sys.check_again")}
          </Button>
        </Stack>
        <Typography sx={{ color: f.muted, mb: 2 }}>{t("autom.sys.intro")}</Typography>

        {loadError != null ? (
          <FriendlyError compact error={loadError} what={t("autom.sys.err")} onRetry={load} />
        ) : !data ? (
          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(2, 1fr)" } }}>
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} variant="rounded" height={120} />)}
          </Box>
        ) : (
          <Stack spacing={2}>
            <Card role="status" sx={{ p: 2, boxShadow: "none", bgcolor: bg[data.overall] ?? f.surface2 }}>
              <Stack direction="row" spacing={1.25} alignItems="center">
                <Emoji name={data.overall === "green" ? "check" : "warning"} size={24} />
                <Box>
                  <Typography sx={{ fontWeight: 800 }}>{t(`autom.sys.overall.${data.overall}`)}</Typography>
                  <Typography variant="caption" sx={{ color: f.muted }}>{t("autom.sys.last_checked", { when: when(data.checked_at) })}</Typography>
                </Box>
              </Stack>
            </Card>
            <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(2, 1fr)" } }}>
              {data.items.map(card)}
            </Box>
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}
