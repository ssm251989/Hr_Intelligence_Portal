import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { automationApi, type AddedFromPool, type TalentPoolItem, type TalentPoolResponse } from "../../api/automationApi";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { useT } from "../../i18n";
import { Emoji, EmptyState, FriendlyError, InfoTip, StatusChip } from "../../ui-kit";

// Part 17.13: "Past candidates who match" -- people already in the database (applied to other
// jobs before) scored against THIS job's rules, so a recruiter can add them in one click.
// Scoring a few hundred people takes a moment, so it runs when asked, not on every open.

const SHOW_FIRST = 10;

export default function TalentPoolPanel({ jobId }: { jobId: string }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { can } = useMeBootstrap();
  const canAdd = can("recruitment.application.create");
  const [data, setData] = useState<TalentPoolResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [showAll, setShowAll] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [added, setAdded] = useState<Record<string, AddedFromPool>>({});
  const [addError, setAddError] = useState<unknown>(null);

  if (!can("recruitment.application.view")) return null;

  const load = () => {
    setLoading(true);
    setLoadError(null);
    automationApi
      .talentPool(jobId)
      .then((r) => {
        setData(r);
        setShowAll(false);
      })
      .catch(setLoadError)
      .finally(() => setLoading(false));
  };

  const add = (item: TalentPoolItem) => {
    setAdding(item.candidate_id);
    setAddError(null);
    automationApi
      .addFromPool(jobId, item.candidate_id)
      .then((r) => setAdded((prev) => ({ ...prev, [item.candidate_id]: r })))
      .catch(setAddError)
      .finally(() => setAdding(null));
  };

  const matches = (item: TalentPoolItem) => !item.knocked_out && item.score >= (data?.threshold ?? 0);
  const rows = data ? (showAll ? data.items : data.items.slice(0, SHOW_FIRST)) : [];

  return (
    <Box sx={{ p: 2, borderRadius: "12px", border: `1px solid ${f.line}`, bgcolor: f.surface }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
        <Emoji name="people" size={20} />
        <Typography sx={{ fontWeight: 700, flex: 1 }}>
          {t("autom.pool.title")}
          <InfoTip text={t("autom.pool.info")} />
        </Typography>
        {data && (
          <Button size="small" onClick={load} disabled={loading}>{t("autom.pool.check_again")}</Button>
        )}
      </Stack>

      {!data && !loading && !loadError && (
        <Stack spacing={1} alignItems="flex-start">
          <Typography variant="body2" sx={{ color: f.muted }}>{t("autom.pool.hint")}</Typography>
          <Button variant="outlined" size="small" startIcon={<Emoji name="magnifier" size={16} />} onClick={load}>{t("autom.pool.find")}</Button>
        </Stack>
      )}

      {loading && (
        <Stack direction="row" spacing={1} alignItems="center" role="status" sx={{ py: 1 }}>
          <CircularProgress size={18} />
          <Typography variant="body2" sx={{ color: f.muted }}>{t("autom.pool.loading")}</Typography>
        </Stack>
      )}

      {loadError != null && !loading && <FriendlyError compact error={loadError} what={t("autom.pool.err")} onRetry={load} />}

      {data && !loading && (
        <Stack spacing={1.25}>
          <Box>
            <Typography sx={{ fontWeight: 800, fontSize: 18 }}>
              {data.matching > 0 ? t("autom.pool.headline", { count: data.matching }) : t("autom.pool.headline_none")}
            </Typography>
            <Typography variant="body2" sx={{ color: f.muted }}>
              {t("autom.pool.checked", { checked: data.checked, threshold: Math.round(data.threshold) })}
            </Typography>
          </Box>

          {addError != null && <FriendlyError compact error={addError} what={t("autom.pool.add_err")} />}

          {data.items.length === 0 ? (
            <EmptyState compact illustration="people-search" title={t("autom.pool.empty")} hint={t("autom.pool.empty_hint")} />
          ) : (
            <Stack spacing={0.75} component="ul" sx={{ listStyle: "none", m: 0, p: 0 }}>
              {rows.map((item) => {
                const done = added[item.candidate_id];
                const good = matches(item);
                return (
                  <Stack key={item.candidate_id} component="li" direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}
                    sx={{ p: 1.25, borderRadius: "10px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography sx={{ fontWeight: 700, color: item.name ? f.ink : f.muted }} noWrap>
                        {item.name || t("autom.pool.no_name")}
                      </Typography>
                      <Typography variant="caption" sx={{ color: f.muted, display: "block" }}>
                        {[
                          item.location,
                          item.years != null ? t("autom.pool.years", { count: Math.round(item.years * 10) / 10 }) : null,
                          item.last_seen ? t("autom.pool.last_seen", { date: new Date(item.last_seen).toLocaleDateString() }) : null,
                        ].filter(Boolean).join(" · ")}
                      </Typography>
                    </Box>
                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                      <StatusChip tone={item.knocked_out ? "coral" : good ? "ok" : "muted"} emoji={item.knocked_out ? "cross" : good ? "check" : "target"}
                        label={item.knocked_out ? t("autom.pool.knocked_out", { score: Math.round(item.score) }) : t("autom.pool.score", { score: Math.round(item.score) })} />
                      <Typography variant="caption" sx={{ color: f.muted }}>
                        {good ? t("autom.pool.above", { threshold: Math.round(data.threshold) }) : t("autom.pool.below", { threshold: Math.round(data.threshold) })}
                      </Typography>
                      {done ? (
                        <Button size="small" variant="outlined" component={RouterLink} to={`/candidates/${done.application_id}`}>
                          {t("autom.pool.open_added")}
                        </Button>
                      ) : canAdd ? (
                        <Button size="small" variant={good ? "contained" : "outlined"} disabled={adding !== null} onClick={() => add(item)}>
                          {adding === item.candidate_id ? t("autom.pool.adding") : t("autom.pool.add")}
                        </Button>
                      ) : null}
                    </Stack>
                  </Stack>
                );
              })}
            </Stack>
          )}

          {data.items.length > SHOW_FIRST && (
            <Button size="small" onClick={() => setShowAll((v) => !v)} sx={{ alignSelf: "flex-start" }}>
              {showAll ? t("autom.pool.show_less") : t("autom.pool.show_all", { count: data.items.length })}
            </Button>
          )}
          {Object.keys(added).length > 0 && (
            <Typography variant="body2" role="status" sx={{ color: f.ok, fontWeight: 600 }}>
              {t("autom.pool.added_note", { count: Object.keys(added).length })}
            </Typography>
          )}
        </Stack>
      )}
    </Box>
  );
}
