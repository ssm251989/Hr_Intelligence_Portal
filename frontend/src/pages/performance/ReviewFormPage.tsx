import { useCallback, useEffect, useRef, useState } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { performanceExtraApi, type ReviewForm, type ReviewPayload, type ReviewSection, type ScalePoint } from "../../api/performanceExtra";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import ConfirmDialog from "../../components/ConfirmDialog";
import { NoAccess, Panel, PerfChip, ProgressBar, useDateFormat, useFresh } from "../../components/performance/shared";
import { useI18n, useT } from "../../i18n";
import { Cell, Emoji, FriendlyError, InfoTip, PageGrid, PageHeader, celebrate, explainError } from "../../ui-kit";

// Part 15.6 (spec L F3, F4): ONE page, every section visible, saved as a draft a moment
// after each change (POST with final=false), submitted with one button. The rating
// scale comes from the cycle; a 5-point scale is the default when none is set.

const AI_FEATURE = "performance.review_draft";
const AUTOSAVE_MS = 1500;

function RatingPicker({ scale, value, onChange, disabled, label }: { scale: ScalePoint[]; value: number | null | undefined; onChange: (v: number | null) => void; disabled: boolean; label: string }) {
  const f = useFresh();
  const t = useT();
  return (
    <Box role="radiogroup" aria-label={label} sx={{ display: "flex", flexWrap: "wrap", gap: 0.75 }}>
      {scale.map((p) => {
        const on = value != null && Number(value) === p.value;
        const text = p.label || t(`performance.scale5.${Math.round(p.value)}`);
        return (
          <Box
            key={p.value}
            component="button"
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            onClick={() => onChange(on ? null : p.value)}
            sx={{
              all: "unset", cursor: disabled ? "default" : "pointer", px: 1.4, py: 0.75, borderRadius: "11px", fontSize: 13, fontWeight: 700,
              border: `1px solid ${on ? f.brand : f.line}`, bgcolor: on ? f.brand : f.surface, color: on ? f.brandInk : f.ink,
              "&:focus-visible": { outline: `2px solid ${f.brand}`, outlineOffset: 2 }, opacity: disabled && !on ? 0.6 : 1,
            }}
          >
            {p.value} · {text}
          </Box>
        );
      })}
    </Box>
  );
}

function sectionTitle(s: ReviewSection, t: (k: string) => string): string {
  const explicit = s.title || s.name || s.label;
  if (explicit) return explicit;
  const key = `performance.section.${s.key}`;
  return t(key) !== key ? t(key) : s.key.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function itemText(item: NonNullable<ReviewSection["items"]>[number]): string {
  return typeof item === "string" ? item : item.label || item.title || item.text || item.key || "";
}

export default function ReviewFormPage() {
  const { reviewId = "" } = useParams();
  const t = useT();
  const f = useFresh();
  const { locale } = useI18n();
  const date = useDateFormat();
  const navigate = useNavigate();
  const { can, aiFeature, loading: bootLoading } = useMeBootstrap();
  const [form, setForm] = useState<ReviewForm | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [scores, setScores] = useState<Record<string, number | null>>({});
  const [goalRatings, setGoalRatings] = useState<Record<string, number | null>>({});
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [comments, setComments] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "pending" | "saving" | "saved" | "failed">("idle");
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiDraft, setAiDraft] = useState<{ summary?: string; bias_flags?: string[] } | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const dirty = useRef(false);
  const timer = useRef<number | undefined>(undefined);

  const load = useCallback(() => {
    setError(null);
    performanceExtraApi
      .reviewForm(reviewId)
      .then((data) => {
        setForm(data);
        setScores(data.review.section_scores ?? {});
        setGoalRatings(data.review.goal_ratings ?? {});
        setAnswers(data.review.answers ?? {});
        setComments(data.review.comments ?? "");
        setAiDraft(data.review.ai_draft);
        dirty.current = false;
      })
      .catch(setError);
  }, [reviewId]);

  useEffect(load, [load]);

  const readOnly = !form || form.review.status === "submitted" || form.cycle?.status !== "active";
  const payload = useCallback((final: boolean): ReviewPayload => ({ section_scores: scores, goal_ratings: goalRatings, answers, comments: comments.trim() || null, final }), [scores, goalRatings, answers, comments]);

  const send = useCallback(
    (final: boolean) => {
      if (!form) return Promise.resolve();
      const body = payload(final);
      return form.submit_as === "me" ? performanceExtraApi.saveMyReview(form.review.id, body) : performanceExtraApi.saveReviewAsAdmin(form.review.id, body);
    },
    [form, payload],
  );

  // Autosave: a moment after the last change, as a draft.
  useEffect(() => {
    if (!dirty.current || readOnly) return;
    setSaveState("pending");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      setSaveState("saving");
      send(false)
        .then(() => {
          setSaveState("saved");
          setSavedAt(new Date());
          setSaveError(null);
        })
        .catch((err) => {
          const e = explainError(err);
          setSaveState("failed");
          setSaveError(`${e.what} ${e.fix}`);
        });
    }, AUTOSAVE_MS);
    return () => window.clearTimeout(timer.current);
  }, [scores, goalRatings, answers, comments, readOnly, send]);

  const touch = <T,>(setter: (fn: (prev: T) => T) => void) => (fn: (prev: T) => T) => {
    dirty.current = true;
    setter(fn);
  };
  const setScore = touch(setScores);
  const setGoal = touch(setGoalRatings);
  const setAnswer = touch(setAnswers);

  const submit = async () => {
    setSubmitting(true);
    window.clearTimeout(timer.current);
    try {
      await send(true);
      setConfirm(false);
      void celebrate(`review.submitted:${form?.review.id}`);
      navigate("/performance");
    } catch (err) {
      const e = explainError(err);
      setSaveError(`${e.what} ${e.fix}`);
      setConfirm(false);
    } finally {
      setSubmitting(false);
    }
  };

  const askAi = async () => {
    if (!form) return;
    setAiBusy(true);
    setAiError(null);
    try {
      const r = await performanceExtraApi.aiDraft(form.review.id);
      setAiDraft(r.ai_draft);
    } catch (err) {
      const e = explainError(err);
      setAiError(`${e.what} ${e.fix}`);
    } finally {
      setAiBusy(false);
    }
  };

  if (bootLoading) return null;
  const title = form ? (form.about_me ? t("performance.review.title_self") : t("performance.review.title_other", { name: form.employee_name || t("performance.someone") })) : t("performance.review.title");

  if (!can("performance.self.view") && !can("performance.review.edit")) {
    return (
      <Box>
        <PageHeader emoji="writing_hand" title={t("performance.review.title")} purpose={t("performance.review.purpose")} />
        <NoAccess what={t("performance.review.title")} />
      </Box>
    );
  }

  const scale: ScalePoint[] = form?.scale?.length ? form.scale : [1, 2, 3, 4, 5].map((v) => ({ value: v, label: null }));
  const sections = form?.cycle?.sections ?? [];
  const filled = sections.filter((s) => (s.key === "goals" ? form?.goals.some((g) => goalRatings[g.id] != null) : scores[s.key] != null)).length;
  const pct = sections.length ? Math.round((100 * filled) / sections.length) : comments ? 100 : 0;
  const timeFmt = (d: Date) => d.toLocaleTimeString(locale === "en" ? "en-IN" : `${locale}-IN`, { hour: "numeric", minute: "2-digit" });
  const saveText =
    saveState === "saving" ? t("performance.review.autosave.saving")
      : saveState === "pending" ? t("performance.review.autosave.pending")
        : saveState === "saved" && savedAt ? t("performance.review.autosave.saved", { time: timeFmt(savedAt) })
          : saveState === "failed" ? t("performance.review.autosave.failed")
            : t("performance.review.autosave.idle");

  return (
    <Box>
      <PageHeader
        emoji="writing_hand"
        title={title}
        purpose={form?.cycle ? t("performance.review.purpose_cycle", { cycle: form.cycle.name, end: date(form.cycle.period_end) }) : t("performance.review.purpose")}
        tourKey="performance-review"
        extra={<Button variant="text" component={RouterLink} to="/performance">{t("performance.review.back")}</Button>}
        primary={!readOnly ? <Button variant="contained" onClick={() => setConfirm(true)} startIcon={<Emoji name="check" size={16} />}>{t("performance.review.submit")}</Button> : undefined}
      />

      {error ? (
        <FriendlyError error={error} onRetry={load} actionLabel={t("performance.review.back")} actionTo="/performance" />
      ) : !form ? (
        <Typography sx={{ color: f.muted }}>{t("performance.loading")}</Typography>
      ) : (
        <PageGrid>
          <Cell span={{ xs: 12, lg: 8 }} sx={{ gap: 2.25, "& > *": { flex: "0 0 auto" } }}>
            {form.review.status === "submitted" && <Alert severity="success" icon={<Emoji name="check" size={18} />}>{t("performance.review.already_submitted", { date: date(form.review.submitted_at) })}</Alert>}
            {form.review.status !== "submitted" && form.cycle?.status !== "active" && <Alert severity="info">{t("performance.review.cycle_closed")}</Alert>}

            {sections.map((s) => (
              <Panel key={s.key} emoji={s.key === "goals" ? "target" : s.key === "values" ? "glowing_star" : s.key === "competencies" ? "tools" : "speech"} title={sectionTitle(s, t)}
                tip={s.weight ? t("performance.review.section_weight", { weight: s.weight }) : undefined}>
                {s.key === "goals" ? (
                  form.goals.length === 0 ? (
                    <Typography sx={{ color: f.muted }}>{t("performance.review.no_goals")}</Typography>
                  ) : (
                    <Stack spacing={2}>
                      {form.goals.map((g) => (
                        <Box key={g.id} sx={{ p: 1.5, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                          <Stack direction={{ xs: "column", md: "row" }} spacing={1} justifyContent="space-between" sx={{ mb: 1 }}>
                            <Typography sx={{ fontWeight: 700 }}>{g.title}</Typography>
                            <Box sx={{ width: 220 }}><ProgressBar value={g.progress_pct} compact /></Box>
                          </Stack>
                          <RatingPicker scale={scale} value={goalRatings[g.id]} disabled={readOnly} label={t("performance.review.rate_goal", { title: g.title })}
                            onChange={(v) => setGoal((prev) => ({ ...prev, [g.id]: v }))} />
                        </Box>
                      ))}
                    </Stack>
                  )
                ) : (
                  <Stack spacing={1.5}>
                    {s.items?.length ? (
                      <Box component="ul" sx={{ m: 0, pl: 2.5, color: f.muted }}>
                        {s.items.map((it, i) => <li key={i}><Typography sx={{ fontSize: 14 }}>{itemText(it)}</Typography></li>)}
                      </Box>
                    ) : null}
                    <RatingPicker scale={scale} value={scores[s.key]} disabled={readOnly} label={t("performance.review.rate_section", { title: sectionTitle(s, t) })}
                      onChange={(v) => setScore((prev) => ({ ...prev, [s.key]: v }))} />
                    <TextField
                      label={t("performance.review.section_notes")}
                      placeholder={t("performance.review.section_notes_placeholder")}
                      helperText={t("performance.review.section_notes_hint")}
                      value={typeof answers[s.key] === "string" ? (answers[s.key] as string) : ""}
                      onChange={(e) => setAnswer((prev) => ({ ...prev, [s.key]: e.target.value }))}
                      multiline
                      minRows={2}
                      disabled={readOnly}
                    />
                  </Stack>
                )}
              </Panel>
            ))}

            <Panel emoji="memo" title={t("performance.review.overall")}>
              <TextField
                label={t("performance.review.comments")}
                placeholder={t("performance.review.comments_placeholder")}
                helperText={t("performance.review.comments_hint")}
                value={comments}
                onChange={(e) => {
                  dirty.current = true;
                  setComments(e.target.value);
                }}
                multiline
                minRows={4}
                fullWidth
                disabled={readOnly}
              />
            </Panel>
          </Cell>

          <Cell span={{ xs: 12, lg: 4 }} sx={{ gap: 2.25, "& > *": { flex: "0 0 auto" } }}>
            <Card sx={{ p: 2.5, position: { lg: "sticky" }, top: { lg: 88 } }}>
              <Stack spacing={1.5}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <PerfChip status={form.review.status} />
                  <Typography sx={{ color: f.muted, fontSize: 13 }}>{t(`performance.stage.${form.review.stage}`)}</Typography>
                </Stack>
                <Box>
                  <Typography sx={{ fontWeight: 700, mb: 0.5 }}>{t("performance.review.progress")}</Typography>
                  <ProgressBar value={pct} label={t("performance.review.progress_words", { done: filled, total: sections.length })} />
                </Box>
                <Stack direction="row" spacing={1} alignItems="center" aria-live="polite">
                  <Emoji name={saveState === "failed" ? "warning" : saveState === "saved" ? "check" : "hourglass"} size={16} />
                  <Typography sx={{ fontSize: 13, color: saveState === "failed" ? f.coral : f.muted }}>{readOnly ? t("performance.review.autosave.readonly") : saveText}</Typography>
                </Stack>
                {saveError && <Alert severity="error">{saveError}</Alert>}
                <Box>
                  <Typography sx={{ fontWeight: 700, fontSize: 14 }}>
                    {t("performance.review.scale_title")}
                    <InfoTip text={t("performance.review.scale_tip")} />
                  </Typography>
                  <Box component="ul" sx={{ m: 0, pl: 2.5, mt: 0.5 }}>
                    {scale.map((p) => <li key={p.value}><Typography sx={{ fontSize: 13 }}>{p.value} — {p.label || t(`performance.scale5.${Math.round(p.value)}`)}</Typography></li>)}
                  </Box>
                </Box>
              </Stack>
            </Card>

            {aiFeature(AI_FEATURE) && form.submit_as === "me" && (
              <Panel emoji="sparkles" title={t("performance.review.ai.title")} tip={t("performance.review.ai.tip")}>
                <Stack spacing={1.5}>
                  {aiDraft?.summary ? (
                    <>
                      <Typography sx={{ whiteSpace: "pre-wrap", fontSize: 14, maxWidth: "70ch" }}>{aiDraft.summary}</Typography>
                      {aiDraft.bias_flags?.length ? (
                        <Alert severity="warning">{t("performance.review.ai.bias", { words: aiDraft.bias_flags.join(", ") })}</Alert>
                      ) : null}
                      {!readOnly && (
                        <Button variant="outlined" onClick={() => {
                          dirty.current = true;
                          setComments((c) => (c ? `${c}\n\n${aiDraft.summary}` : aiDraft.summary ?? ""));
                        }}>{t("performance.review.ai.use")}</Button>
                      )}
                    </>
                  ) : (
                    <Typography sx={{ color: f.muted, fontSize: 14 }}>{t("performance.review.ai.intro")}</Typography>
                  )}
                  {aiError && <Alert severity="error">{aiError}</Alert>}
                  {!readOnly && (
                    <Button variant="text" onClick={askAi} disabled={aiBusy} startIcon={<Emoji name="sparkles" size={16} />}>
                      {aiBusy ? t("performance.review.ai.working") : aiDraft?.summary ? t("performance.review.ai.again") : t("performance.review.ai.ask")}
                    </Button>
                  )}
                </Stack>
              </Panel>
            )}
          </Cell>
        </PageGrid>
      )}

      <ConfirmDialog
        open={confirm}
        title={t("performance.review.confirm_title")}
        message={t("performance.review.confirm_body", { done: filled, total: sections.length })}
        confirmLabel={t("performance.review.submit")}
        cancelLabel={t("action.cancel")}
        confirming={submitting}
        onConfirm={submit}
        onCancel={() => setConfirm(false)}
      />
    </Box>
  );
}
