import { useCallback, useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import CloseIcon from "@mui/icons-material/Close";
import { useTheme } from "@mui/material/styles";

import { onboardingExtraApi, type JoinerDetail, type PlanTemplateRow } from "../../api/onboardingExtra";
import { useI18n } from "../../i18n";
import { Emoji, EmptyState, FriendlyError, ProgressRing, StatusChip, Timeline, UserAvatar } from "../../ui-kit";
import { RejectDialog, WelcomeEditor } from "./OnboardingDialogs";
import { JoinerStatusChip, ownerText, useDateText } from "./shared";

const KIND_EMOJI: Record<string, string> = { form: "memo", document: "page", policy: "clipboard" };
const EVENT_EMOJI: Record<string, string> = { created: "sparkles", joining_date_changed: "calendar", no_show: "pause", revoked: "cross", joined: "party" };

export async function openDocument(id: string): Promise<boolean> {
  const blob = await onboardingExtraApi.documentFile(id);
  if (!blob) return false;
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
  return true;
}

// Everything about one joiner: checklist, documents (view / approve / send back), plan
// tasks, what their welcome page shows (buddy, agenda, message) and what has happened.
export default function JoinerDrawer({
  caseId, onClose, onChanged, canEdit, canTasks, canPlans,
}: {
  caseId: string | null;
  onClose: () => void;
  onChanged: () => void;
  canEdit: boolean;
  canTasks: boolean;
  canPlans: boolean;
}) {
  const f = useTheme().palette.fresh;
  const { t, locale } = useI18n();
  const d = useDateText();
  const [tab, setTab] = useState("checklist");
  const [data, setData] = useState<JoinerDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [rejecting, setRejecting] = useState<{ id: string; label: string } | null>(null);
  const [templates, setTemplates] = useState<PlanTemplateRow[] | null>(null);
  const [template, setTemplate] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [fileMissing, setFileMissing] = useState(false);

  const load = useCallback(() => {
    if (!caseId) return;
    setError(null);
    onboardingExtraApi.detail(caseId, locale).then(setData).catch(setError);
  }, [caseId, locale]);

  useEffect(() => {
    setData(null);
    setTab("checklist");
    setActionError(null);
    load();
  }, [load]);

  useEffect(() => {
    if (tab === "tasks" && canPlans && templates === null) {
      onboardingExtraApi.planTemplates().then((rows) => {
        const active = rows.filter((r) => r.is_active);
        setTemplates(active);
        setTemplate(active[0]?.code ?? "");
      }).catch(() => setTemplates([]));
    }
  }, [tab, canPlans, templates]);

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setActionError(null);
    try {
      await fn();
      load();
      onChanged();
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(null);
    }
  };

  const view = async (id: string) => {
    setFileMissing(false);
    if (!(await openDocument(id))) setFileMissing(true);
  };

  return (
    <Drawer anchor="right" open={Boolean(caseId)} onClose={onClose} slotProps={{ paper: { sx: { width: { xs: "100%", sm: 560 }, p: 0 } } }}>
      <Stack direction="row" alignItems="center" sx={{ p: 2, borderBottom: `1px solid ${f.line}` }}>
        <Typography variant="h6" sx={{ flex: 1, fontWeight: 800 }}>{t("onboarding.drawer.title")}</Typography>
        <IconButton aria-label={t("action.close")} onClick={onClose}><CloseIcon /></IconButton>
      </Stack>
      <Box sx={{ p: 2.5, overflowY: "auto" }}>
        {error ? <FriendlyError error={error} onRetry={load} compact />
          : !data ? <Box sx={{ display: "grid", placeItems: "center", py: 8 }}><CircularProgress aria-label={t("onboarding.loading")} /></Box>
            : (
              <Stack spacing={2.5}>
                <Stack direction="row" spacing={2} alignItems="center">
                  <UserAvatar name={data.name} size={56} />
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography sx={{ fontWeight: 800, fontSize: 18 }}>{data.name}</Typography>
                    <Typography sx={{ color: f.muted, fontSize: 13 }}>{[data.role, data.department].filter(Boolean).join(" · ") || data.email}</Typography>
                    <Typography sx={{ fontSize: 13, mt: 0.5 }}><Emoji name="calendar" size={14} /> {t("onboarding.drawer.joins", { date: d.long(data.joining_date) })}</Typography>
                    <Box sx={{ mt: 0.75 }}><JoinerStatusChip status={data.status} t={t} /></Box>
                  </Box>
                  <ProgressRing value={data.readiness_percent} size={84} thickness={10} label={`${data.readiness_percent}%`} caption={t("onboarding.card.ring", { percent: data.readiness_percent, name: data.name })} />
                </Stack>

                {actionError ? <FriendlyError error={actionError} compact /> : null}
                {fileMissing && <FriendlyError what={t("onboarding.docs.file_missing")} fix={t("onboarding.docs.file_missing_fix")} compact />}

                <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" allowScrollButtonsMobile>
                  <Tab value="checklist" label={t("onboarding.drawer.tab_checklist")} />
                  <Tab value="documents" label={t("onboarding.drawer.tab_documents", { count: data.documents.length })} />
                  <Tab value="tasks" label={t("onboarding.drawer.tab_tasks", { count: data.tasks.length })} />
                  <Tab value="welcome" label={t("onboarding.drawer.tab_welcome")} />
                  <Tab value="history" label={t("onboarding.drawer.tab_history")} />
                </Tabs>

                {tab === "checklist" && (
                  data.checklist.length === 0
                    ? <EmptyState compact illustration="completed-tasks" title={t("onboarding.drawer.no_checklist")} hint={t("onboarding.drawer.no_checklist_hint")} />
                    : (
                      <Stack component="ul" spacing={1} sx={{ listStyle: "none", p: 0, m: 0 }}>
                        {data.checklist.map((c) => (
                          <Stack component="li" key={`${c.kind}:${c.code}`} direction="row" spacing={1.5} alignItems="center" sx={{ p: 1.25, borderRadius: "12px", bgcolor: c.done ? f.okSoft : f.surface2, border: `1px solid ${c.done ? "transparent" : f.line}` }}>
                            <Emoji name={KIND_EMOJI[c.kind]} size={20} />
                            <Box sx={{ flex: 1, minWidth: 0 }}>
                              <Typography sx={{ fontWeight: 600 }}>{c.label}</Typography>
                              <Typography sx={{ fontSize: 12, color: f.muted }}>{t(`onboarding.kind.${c.kind}`)}</Typography>
                            </Box>
                            {c.done ? <StatusChip status="done" />
                              : c.kind === "document" && c.status === "pending" ? <StatusChip tone="sun" emoji="eyes" label={t("onboarding.docs.to_check")} />
                                : c.kind === "document" && c.status === "rejected" ? <StatusChip tone="coral" emoji="cross" label={t("onboarding.docs.sent_back")} />
                                  : <StatusChip tone="muted" emoji="hourglass" label={t("onboarding.drawer.not_yet")} />}
                          </Stack>
                        ))}
                      </Stack>
                    )
                )}

                {tab === "documents" && (
                  data.documents.length === 0
                    ? <EmptyState compact illustration="files-uploading" title={t("onboarding.docs.none_uploaded")} hint={t("onboarding.docs.none_uploaded_hint")} />
                    : (
                      <Stack spacing={1}>
                        {data.documents.map((doc) => (
                          <Box key={doc.id} sx={{ p: 1.5, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                            <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: "wrap", rowGap: 1 }}>
                              <Emoji name="page" size={20} />
                              <Typography sx={{ fontWeight: 600, flex: 1, minWidth: 140 }}>{doc.label}</Typography>
                              {doc.status === "verified" ? <StatusChip tone="ok" emoji="check" label={t("onboarding.docs.verified")} />
                                : doc.status === "rejected" ? <StatusChip tone="coral" emoji="cross" label={t("onboarding.docs.sent_back")} />
                                  : <StatusChip tone="sun" emoji="eyes" label={t("onboarding.docs.to_check")} />}
                            </Stack>
                            {doc.uploaded_at && <Typography sx={{ fontSize: 12, color: f.muted, mt: 0.5 }}>{t("onboarding.docs.uploaded_at", { when: d.when(doc.uploaded_at) })}</Typography>}
                            {doc.rejection_reason && <Typography sx={{ fontSize: 13, mt: 0.5 }}>“{doc.rejection_reason}”</Typography>}
                            <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                              {doc.has_file && <Button size="small" variant="outlined" onClick={() => view(doc.id)}>{t("onboarding.docs.view")}</Button>}
                              {canEdit && doc.status === "pending" && (
                                <>
                                  <Button size="small" variant="contained" disabled={busy === doc.id} onClick={() => run(doc.id, () => onboardingExtraApi.verifyDocument(doc.id, true))}>{t("onboarding.docs.approve")}</Button>
                                  <Button size="small" color="error" onClick={() => setRejecting({ id: doc.id, label: doc.label })}>{t("onboarding.docs.reject")}</Button>
                                </>
                              )}
                            </Stack>
                          </Box>
                        ))}
                      </Stack>
                    )
                )}

                {tab === "tasks" && (
                  data.tasks.length === 0 ? (
                    <Box>
                      <EmptyState compact illustration="to-do-list" title={t("onboarding.tasks.no_plan")} hint={t("onboarding.tasks.no_plan_hint")} />
                      {canPlans && templates && templates.length > 0 && (
                        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "flex-start" }}>
                          <TextField select size="small" label={t("onboarding.tasks.plan")} value={template} onChange={(e) => setTemplate(e.target.value)} helperText={t("onboarding.tasks.plan_hint")} sx={{ flex: 1 }}>
                            {templates.map((p) => <MenuItem key={p.code} value={p.code}>{p.name}</MenuItem>)}
                          </TextField>
                          <Button variant="contained" disabled={!template || busy === "plan"} onClick={() => run("plan", () => onboardingExtraApi.generatePlan(data.case_id, template))}>{t("onboarding.tasks.make_plan")}</Button>
                        </Stack>
                      )}
                      {canPlans && templates && templates.length === 0 && (
                        <Typography sx={{ color: f.muted, fontSize: 13, textAlign: "center" }}>{t("onboarding.tasks.no_templates")}</Typography>
                      )}
                    </Box>
                  ) : (
                    <Stack component="ul" spacing={1} sx={{ listStyle: "none", p: 0, m: 0 }}>
                      {data.tasks.map((task) => {
                        const finished = task.status === "done" || task.status === "skipped";
                        const late = !finished && task.due_date < new Date().toISOString().slice(0, 10);
                        return (
                          <Stack component="li" key={task.id} direction="row" spacing={1.5} alignItems="center" sx={{ p: 1.25, borderRadius: "12px", bgcolor: finished ? f.okSoft : f.surface2, border: `1px solid ${late ? f.coral : f.line}` }}>
                            <Box sx={{ flex: 1, minWidth: 0 }}>
                              <Typography sx={{ fontWeight: 600 }}>{task.title}</Typography>
                              <Typography sx={{ fontSize: 12, color: f.muted }}>{t("onboarding.tasks.meta", { owner: ownerText(task.owner_role, t), date: d.day(task.due_date) })}</Typography>
                            </Box>
                            {finished ? <StatusChip status="done" />
                              : task.status === "blocked" ? <StatusChip tone="muted" emoji="lock" label={t("onboarding.tasks.waiting")} />
                                : late ? <StatusChip status="overdue" />
                                  : canTasks ? <Button size="small" variant="outlined" disabled={busy === task.id} onClick={() => run(task.id, () => onboardingExtraApi.completeTask(task.id))}>{t("onboarding.tasks.mark_done")}</Button>
                                    : <StatusChip tone="sun" emoji="hourglass" label={t("onboarding.drawer.not_yet")} />}
                            {late && canTasks && <Button size="small" variant="outlined" disabled={busy === task.id} onClick={() => run(task.id, () => onboardingExtraApi.completeTask(task.id))}>{t("onboarding.tasks.mark_done")}</Button>}
                          </Stack>
                        );
                      })}
                    </Stack>
                  )
                )}

                {tab === "welcome" && (
                  canEdit ? (
                    <Box>
                      <Typography sx={{ color: f.muted, mb: 2 }}>{t("onboarding.welcome.intro", { name: data.first_name })}</Typography>
                      <WelcomeEditor key={data.case_id} initial={data.welcome} onSave={async (w) => { await onboardingExtraApi.saveWelcome(data.case_id, w); load(); }} />
                    </Box>
                  ) : <Typography sx={{ color: f.muted }}>{t("onboarding.welcome.read_only")}</Typography>
                )}

                {tab === "history" && (
                  <Timeline
                    empty={t("onboarding.history.empty")}
                    items={[...data.history].reverse().map((h, i) => ({
                      id: `${i}`,
                      emoji: EVENT_EMOJI[h.event] ?? "memo",
                      title: h.event === "joining_date_changed" && h.old && h.new
                        ? t("onboarding.history.date_changed", { old: d.day(h.old), new: d.day(h.new) })
                        : t(`onboarding.history.${h.event}`) === `onboarding.history.${h.event}` ? h.event.replace(/_/g, " ") : t(`onboarding.history.${h.event}`),
                      meta: [h.at ? d.when(h.at) : null, h.actor && h.actor !== "system" ? h.actor : null, h.reason ? `“${h.reason}”` : null].filter(Boolean).join(" · "),
                    }))}
                  />
                )}
              </Stack>
            )}
      </Box>
      <RejectDialog
        label={rejecting?.label ?? null}
        onClose={() => setRejecting(null)}
        onConfirm={async (reason) => {
          if (!rejecting) return;
          await onboardingExtraApi.verifyDocument(rejecting.id, false, reason);
          setRejecting(null);
          load();
          onChanged();
        }}
      />
    </Drawer>
  );
}
