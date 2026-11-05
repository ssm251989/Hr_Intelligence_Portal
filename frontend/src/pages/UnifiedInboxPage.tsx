import { useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Skeleton from "@mui/material/Skeleton";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { candidateEmailsApi } from "../api/candidateEmailsApi";
import { experienceApi, intelligenceApi, workflowApi, type InboxItem, type InboxRow } from "../api/client";
import { t as tr, useT, type TFunction } from "../i18n";
import RefreshButton from "../components/RefreshButton";
import { EmptyState, Emoji, FriendlyError, humanise, PageHeader, StatusChip } from "../ui-kit";

// Part 5B section 3's Unified Inbox + Part 14 section 4 + Part 15.6: every approval / task
// waiting on the current user, across every module, grouped by what kind of request it is,
// each with a due chip. Approve or decline (with an optional comment) right here; approval
// emails keep working unchanged. AI suggestions, reviews and exit clearance items sit below.

const DAY = 24 * 60 * 60 * 1000;

function DueChip({ due }: { due: string | null }) {
  const t = useT();
  if (!due) return <StatusChip tone="muted" emoji="calendar" label={t("approvalsPage.no_due")} />;
  const at = new Date(due);
  const left = at.getTime() - Date.now();
  if (left < 0) return <StatusChip status="overdue" label={t("approvalsPage.overdue_since", { when: at.toLocaleDateString() })} />;
  if (left < DAY) {
    const hours = Math.max(1, Math.round(left / 3_600_000));
    return <StatusChip status="due_soon" label={t("approvalsPage.hours_left", { count: hours })} />;
  }
  return <StatusChip tone="sky" emoji="calendar" label={t("approvalsPage.due_on", { when: at.toLocaleDateString() })} />;
}

function stepName(t: TFunction, node: string) {
  const key = `approvalsPage.step.${node}`;
  const x = t(key);
  return x !== key ? x : humanise(node);
}

function ActDialog({ row, action, onClose, onDone, onError }: {
  row: InboxRow | null;
  action: "approve" | "reject" | null;
  onClose: () => void;
  onDone: (action: "approve" | "reject") => void;
  onError: (error: unknown) => void;
}) {
  const t = useT();
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => setComment(""), [row, action]);

  if (!row || !action) return null;

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await workflowApi.actOnStep(row.step_id, action, comment || undefined);
      onDone(action);
      onClose();
    } catch (err) {
      onError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth aria-labelledby="act-title">
      <DialogTitle id="act-title">
        {action === "approve" ? t("approvalsPage.approve_title", { name: row.definition_name }) : t("approvalsPage.decline_title", { name: row.definition_name })}
      </DialogTitle>
      <DialogContent>
        <Typography sx={{ color: "text.secondary", mb: 1.5 }}>
          {action === "approve" ? t("approvalsPage.approve_body") : t("approvalsPage.decline_body")}
        </Typography>
        <TextField
          label={action === "approve" ? t("approvalsPage.comment_optional") : t("approvalsPage.comment_reason")}
          placeholder={action === "approve" ? t("approvalsPage.comment_eg_ok") : t("approvalsPage.comment_eg_no")}
          helperText={t("approvalsPage.comment_hint")}
          multiline minRows={2} fullWidth value={comment} onChange={(e) => setComment(e.target.value)} sx={{ mt: 1 }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" color={action === "approve" ? "success" : "error"} onClick={handleSubmit} disabled={submitting}>
          {submitting ? t("approvalsPage.sending") : action === "approve" ? t("approvalsPage.approve") : t("approvalsPage.decline")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

const KIND_EMOJI: Record<string, string> = { ai_suggestion: "robot", review: "memo", clearance: "door", copilot_question: "speech", candidate_email: "envelope" };

export default function UnifiedInboxPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [rows, setRows] = useState<InboxRow[]>([]);
  const [others, setOthers] = useState<InboxItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [acting, setActing] = useState<{ row: InboxRow; action: "approve" | "reject" } | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    Promise.all([
      workflowApi.inbox().then(setRows),
      experienceApi.inbox().then((items) => setOthers(items.filter((r) => r.kind !== "approval"))).catch(() => setOthers([])),
    ])
      .catch(setError)
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const groups = useMemo(() => {
    const map = new Map<string, InboxRow[]>();
    [...rows]
      .sort((a, b) => (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999"))
      .forEach((r) => map.set(r.definition_name, [...(map.get(r.definition_name) ?? []), r]));
    return [...map.entries()];
  }, [rows]);

  const decide = (item: InboxItem, action: "approve" | "reject") =>
    intelligenceApi
      .decideSuggestion(item.id, action)
      .then(() => {
        setToast(item.kind === "copilot_question" ? t("approvalsPage.done_marked") : action === "approve" ? t("approvalsPage.done_approved") : t("approvalsPage.done_declined"));
        load();
      })
      .catch(setError);

  const overdue = rows.filter((r) => r.due_at && new Date(r.due_at).getTime() < Date.now()).length;
  const purpose = loading ? t("approvalsPage.purpose") : rows.length + others.length === 0
    ? t("approvalsPage.purpose")
    : `${t("approvalsPage.waiting", { count: rows.length + others.length })}${overdue ? ` · ${t("approvalsPage.overdue_count", { count: overdue })}` : ""}`;

  return (
    <Box>
      <PageHeader emoji="check" title={t("approvalsPage.title")} purpose={purpose} tourKey="approvals"
        primary={<RefreshButton loading={loading} onRefresh={load} />} />

      {error !== null && <Box sx={{ mb: 2 }}><FriendlyError error={error} onRetry={load} compact /></Box>}

      {loading && rows.length === 0 ? (
        <Stack spacing={1.5}>{[0, 1, 2].map((i) => <Skeleton key={i} variant="rounded" height={88} />)}</Stack>
      ) : groups.length === 0 && others.length > 0 ? (
        // Part 23.3e: the header said "11 waiting on you" right above "Nothing waiting on you" - with only
        // "Also for you" items (candidate emails, to-dos) the big empty card is left out
        null
      ) : groups.length === 0 ? (
        <Card sx={{ mb: 2.5 }}>
          <EmptyState illustration="completed-tasks" title={t("approvalsPage.empty")} hint={t("approvalsPage.empty_hint")} />
        </Card>
      ) : (
        <Stack spacing={2.5} sx={{ mb: 3 }} data-tour="approvals-list">
          {groups.map(([type, items]) => (
            <Card key={type} component="section" sx={{ p: 2.25 }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
                <Emoji name="clipboard" size={18} />
                <Typography component="h2" sx={{ fontWeight: 800, fontSize: 16, flex: 1 }}>
                  {type}
                  <Box component="span" sx={{ color: f.muted, fontWeight: 500, fontSize: 13, ml: 1 }}>{t("approvalsPage.requests", { count: items.length })}</Box>
                </Typography>
                <Typography variant="caption" sx={{ color: f.muted }}>{tr("approvals.request_type")}</Typography>
              </Stack>
              <Stack spacing={1}>
                {items.map((row) => (
                  <Box key={row.step_id}
                    sx={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 1.5, p: "12px 14px", borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                    <Box sx={{ flex: "1 1 240px", minWidth: 0 }}>
                      <Typography sx={{ fontWeight: 700 }}>{humanise(row.entity_type)}</Typography>
                      <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("approvalsPage.your_step", { step: stepName(t, row.node_id) })}</Typography>
                    </Box>
                    <DueChip due={row.due_at} />
                    <Stack direction="row" spacing={1}>
                      <Button size="small" variant="contained" color="success" onClick={() => setActing({ row, action: "approve" })} startIcon={<Emoji name="check" size={14} />}>
                        {t("approvalsPage.approve")}
                      </Button>
                      <Button size="small" variant="outlined" color="error" onClick={() => setActing({ row, action: "reject" })}>
                        {t("approvalsPage.decline")}
                      </Button>
                    </Stack>
                  </Box>
                ))}
              </Stack>
            </Card>
          ))}
        </Stack>
      )}

      <Card component="section" sx={{ p: 2.25 }}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
          <Emoji name="inbox" size={18} />
          <Typography component="h2" sx={{ fontWeight: 800, fontSize: 16 }}>{t("approvalsPage.also")}</Typography>
        </Stack>
        {others.length === 0 ? (
          <Typography sx={{ color: f.muted }}>{t("approvalsPage.also_empty")}</Typography>
        ) : (
          <Stack spacing={1}>
            {others.map((item) => (
              <Box key={`${item.kind}-${item.id}`} data-testid={item.kind === "candidate_email" ? `ce-${item.id}` : undefined}
                sx={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 1.5, p: "12px 14px", borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}`,
                  // Part 22.3: candidate emails stand out -- coloured left border, envelope, "Candidate email" chip, unread = bold
                  ...(item.kind === "candidate_email" ? { borderLeft: `5px solid ${f.sky}`, bgcolor: f.skySoft } : {}) }}>
                <Emoji name={KIND_EMOJI[item.kind] ?? "label"} size={20} />
                <Box sx={{ flex: "1 1 240px", minWidth: 0 }}>
                  {item.kind === "candidate_email" && (
                    <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 0.25 }}>
                      <Chip size="small" color="info" label={t("approvalsPage.kind.candidate_email")} />
                      {!item.linked && <Chip size="small" color="warning" variant="outlined" label={t("candidateEmails.card.not_linked")} />}
                      {item.received_at && <Typography sx={{ fontSize: 12, color: f.muted }}>{new Date(item.received_at).toLocaleString()}</Typography>}
                    </Stack>
                  )}
                  <Typography sx={{ fontWeight: item.kind === "candidate_email" && !item.unread ? 500 : 700 }}>{item.title}</Typography>
                  {item.kind === "candidate_email" && item.summary && (
                    <Typography sx={{ fontSize: 14, fontWeight: item.unread ? 700 : 400 }}>{item.summary}</Typography>
                  )}
                  <Typography sx={{ color: f.muted, fontSize: 13 }}>
                    {(() => { const k = `approvalsPage.kind.${item.kind}`; const x = t(k); return x !== k ? x : humanise(item.kind); })()}
                    {item.subtitle ? ` · ${item.subtitle}` : ""}
                  </Typography>
                </Box>
                {item.due_at && <DueChip due={item.due_at} />}
                {item.kind === "candidate_email" ? (
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    <Button size="small" variant="outlined" component={RouterLink} to={item.path}>{t("approvalsPage.open")}</Button>
                    <Button size="small" variant="outlined" component={RouterLink} to={`${item.path}&reply=1`}>{t("approvalsPage.reply")}</Button>
                    {!item.linked && <Button size="small" variant="outlined" component={RouterLink} to={`${item.path}&link=1`}>{t("approvalsPage.link")}</Button>}
                    <Button size="small" variant="contained" onClick={() => candidateEmailsApi.setDone(item.id, true)
                      .then(() => { setToast(t("approvalsPage.done_marked")); load(); window.dispatchEvent(new Event("approvals-changed")); }).catch(setError)}>
                      {t("approvalsPage.mark_done")}
                    </Button>
                  </Stack>
                ) : item.kind === "copilot_question" ? (
                  <Stack direction="row" spacing={1}>
                    {/* Part 22.1: a question the HR assistant handed to HR -- reply by email, then mark done */}
                    <Button size="small" variant="outlined" component="a" href={item.path}>{t("approvalsPage.reply")}</Button>
                    <Button size="small" variant="contained" onClick={() => decide(item, "approve")}>{t("approvalsPage.mark_done")}</Button>
                  </Stack>
                ) : item.kind === "ai_suggestion" ? (
                  <Stack direction="row" spacing={1}>
                    <Button size="small" variant="contained" color="success" onClick={() => decide(item, "approve")}>{t("approvalsPage.approve")}</Button>
                    <Button size="small" variant="outlined" color="error" onClick={() => decide(item, "reject")}>{t("approvalsPage.decline")}</Button>
                  </Stack>
                ) : (
                  <Button size="small" variant="outlined" component={RouterLink} to={item.path}>{t("approvalsPage.open")}</Button>
                )}
              </Box>
            ))}
          </Stack>
        )}
      </Card>

      <ActDialog row={acting?.row ?? null} action={acting?.action ?? null} onClose={() => setActing(null)}
        onDone={(a) => { setToast(a === "approve" ? t("approvalsPage.done_approved") : t("approvalsPage.done_declined")); load(); }} onError={setError} />
      <Snackbar open={Boolean(toast)} autoHideDuration={4000} onClose={() => setToast(null)} message={toast ?? ""} />
    </Box>
  );
}
