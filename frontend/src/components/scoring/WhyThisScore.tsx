import { Fragment, useEffect, useState } from "react";
import CancelIcon from "@mui/icons-material/Cancel";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { scoringApi, type WhyThisScore as Why } from "../../api/scoringApi";
import { useI18n, useT } from "../../i18n";
import { FriendlyError, InfoTip } from "../../ui-kit";

// Part 17.5 "Why this score": every factor of the Match score with its weight, what we found
// for this candidate, the points it earned and the resume lines behind it; the knock-out rules;
// and the total against the shortlist threshold. All from GET /scoring/applications/{id}/why.

export default function WhyThisScore({ applicationId, refreshKey }: { applicationId: string; refreshKey?: unknown }) {
  const t = useT();
  const { locale } = useI18n();
  const f = useTheme().palette.fresh;
  const [why, setWhy] = useState<Why | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const load = () => {
    setError(null);
    scoringApi.why(applicationId).then(setWhy).catch(setError);
  };
  useEffect(load, [applicationId, refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const header = (
    <Typography variant="h6" component="h2" sx={{ fontWeight: 700 }}>
      {t("scoring.why.title")}
      <InfoTip text={t("scoring.why.info")} />
    </Typography>
  );

  if (error) return <Card sx={{ p: 2.25 }}>{header}<FriendlyError compact error={error} what={t("scoring.why.err")} onRetry={load} /></Card>;
  if (!why) return <Card sx={{ p: 2.25 }}>{header}<CircularProgress size={20} aria-label={t("scoring.loading")} /></Card>;

  const score = why.score != null ? Math.round(why.score) : null;
  const scope = why.rules_scope === "job" ? t("scoring.why.scope_job") : why.rules_scope === "company" ? t("scoring.why.scope_company") : t("scoring.why.scope_preset");
  const when = why.scored_at ? new Date(why.scored_at).toLocaleString(locale === "en" ? "en-IN" : `${locale}-IN`, { dateStyle: "medium", timeStyle: "short" }) : null;

  return (
    <Card sx={{ p: 2.25 }} data-testid="why-this-score">
      <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "baseline" }} spacing={1} sx={{ mb: 1 }}>
        {header}
        <Typography sx={{ fontSize: 12, color: f.muted }}>
          {why.rules_version != null ? t("scoring.why.rules_version", { version: why.rules_version, scope }) : scope}
          {when ? ` · ${t("scoring.why.scored_at", { when })}` : ""}
        </Typography>
      </Stack>

      {why.not_saved && <Alert severity="info" sx={{ mb: 1.5 }}>{t("scoring.why.not_saved")}</Alert>}

      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}
        sx={{ p: 1.5, mb: 1.5, borderRadius: "10px", bgcolor: why.knocked_out ? f.coralSoft : why.above_threshold ? f.okSoft : f.surface2 }}>
        <Typography sx={{ fontSize: 30, fontWeight: 800, lineHeight: 1 }}>{score ?? "—"}</Typography>
        <Box>
          <Typography sx={{ fontWeight: 700 }}>{t("scoring.why.match_score")}</Typography>
          <Typography sx={{ fontSize: 13 }}>
            {why.knocked_out
              ? t("scoring.why.knocked_out")
              : why.above_threshold
                ? t("scoring.why.above", { threshold: why.threshold })
                : t("scoring.why.below", { threshold: why.threshold })}
            {why.threshold_from === "job" ? ` ${t("scoring.why.threshold_job")}` : ""}
          </Typography>
        </Box>
      </Stack>

      {why.factors.length === 0 ? (
        <Typography sx={{ color: f.muted }}>{t("scoring.why.no_factors")}</Typography>
      ) : (
        <Box sx={{ overflowX: "auto" }}>
          <Table size="small" aria-label={t("scoring.why.table")}>
            <TableHead>
              <TableRow>
                <TableCell>{t("scoring.why.col.factor")}</TableCell>
                <TableCell align="right">{t("scoring.why.col.weight")}</TableCell>
                <TableCell>{t("scoring.why.col.value")}</TableCell>
                <TableCell sx={{ minWidth: 160 }}>{t("scoring.why.col.points")}</TableCell>
                <TableCell padding="checkbox" />
              </TableRow>
            </TableHead>
            <TableBody>
              {why.factors.map((row) => {
                const isOpen = Boolean(open[row.key]);
                const share = row.weight > 0 ? Math.max(0, Math.min(1, row.points / row.weight)) : 0;
                return (
                  <Fragment key={row.key}>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 600 }}>{t(`scoring.factor.${row.key}`)}</TableCell>
                      <TableCell align="right">{row.weight}%</TableCell>
                      <TableCell sx={{ color: row.known ? f.ink : f.muted, fontSize: 13 }}>
                        {row.value || "—"}
                        {!row.known && <Typography component="span" sx={{ display: "block", fontSize: 11.5, color: f.muted }}>{t("scoring.why.unknown")}</Typography>}
                      </TableCell>
                      <TableCell>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Box sx={{ flex: 1, height: 8, borderRadius: 4, bgcolor: f.line, overflow: "hidden" }} role="img"
                            aria-label={t("scoring.why.points_of", { points: row.points, weight: row.weight })}>
                            <Box sx={{ width: `${share * 100}%`, height: "100%", bgcolor: share >= 0.7 ? f.ok : share >= 0.4 ? f.sun : f.coral }} />
                          </Box>
                          <Typography sx={{ fontSize: 13, fontWeight: 700, minWidth: 64, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                            {t("scoring.why.points_of", { points: row.points, weight: row.weight })}
                          </Typography>
                        </Stack>
                      </TableCell>
                      <TableCell padding="checkbox">
                        {row.evidence.length > 0 && (
                          <IconButton size="small" aria-expanded={isOpen} aria-label={t("scoring.why.evidence_toggle", { name: t(`scoring.factor.${row.key}`) })}
                            onClick={() => setOpen((o) => ({ ...o, [row.key]: !isOpen }))}>
                            {isOpen ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                          </IconButton>
                        )}
                      </TableCell>
                    </TableRow>
                    {isOpen && row.evidence.length > 0 && (
                      <TableRow>
                        <TableCell colSpan={5} sx={{ bgcolor: f.surface2 }}>
                          <Typography sx={{ fontSize: 12, fontWeight: 700, color: f.muted, mb: 0.5 }}>{t("scoring.why.evidence")}</Typography>
                          <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                            {row.evidence.map((line, i) => <Box component="li" key={i} sx={{ fontSize: 13 }}>{line}</Box>)}
                          </Box>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
              <TableRow>
                <TableCell sx={{ fontWeight: 800 }}>{t("scoring.why.total")}</TableCell>
                <TableCell align="right" sx={{ fontWeight: 800 }}>{why.factors.reduce((s, r) => s + r.weight, 0)}%</TableCell>
                <TableCell />
                <TableCell sx={{ fontWeight: 800 }}>{score ?? "—"}</TableCell>
                <TableCell padding="checkbox" />
              </TableRow>
            </TableBody>
          </Table>
        </Box>
      )}

      {why.knockouts.length > 0 && (
        <Box sx={{ mt: 2 }}>
          <Typography sx={{ fontWeight: 700, mb: 0.75 }}>{t("scoring.why.knockouts")}</Typography>
          <Stack spacing={0.5}>
            {why.knockouts.map((k, i) => (
              <Stack key={i} direction="row" spacing={1} alignItems="center">
                {k.passed ? <CheckCircleIcon fontSize="small" sx={{ color: f.ok }} /> : <CancelIcon fontSize="small" sx={{ color: f.coral }} />}
                <Typography sx={{ fontSize: 13.5 }}>
                  <b>{k.label || t(`scoring.ko.${k.type}`)}</b> — {k.passed ? t("scoring.why.ko_passed") : t("scoring.why.ko_failed", { reason: k.reason })}
                </Typography>
              </Stack>
            ))}
          </Stack>
        </Box>
      )}
    </Card>
  );
}
