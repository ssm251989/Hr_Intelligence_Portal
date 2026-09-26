import { useCallback, useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Skeleton from "@mui/material/Skeleton";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { onboardingExtraApi, type JoinerCard as JoinerCardData, type OnboardingBoard } from "../../api/onboardingExtra";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import JoinerCard, { type JoinerAction } from "../../components/onboarding/JoinerCard";
import JoinerDrawer, { openDocument } from "../../components/onboarding/JoinerDrawer";
import { CloseDialog, DateDialog, LinkDialog, RejectDialog, StartDialog } from "../../components/onboarding/OnboardingDialogs";
import { joinGroup, ownerText, useDateText, type JoinGroup } from "../../components/onboarding/shared";
import { useI18n } from "../../i18n";
import { celebrate, Cell, Emoji, EmptyState, FriendlyError, InfoTip, PageGrid, PageHeader, StatTile, StatusChip, UserAvatar } from "../../ui-kit";

const GROUPS: { key: JoinGroup; emoji: string }[] = [
  { key: "passed", emoji: "alarm_clock" },
  { key: "this_week", emoji: "fire" },
  { key: "next_week", emoji: "calendar" },
  { key: "later", emoji: "seedling" },
];

// Part 15.6 (L-P3, P4, P6): the HR view of everyone who is about to join -- cards grouped by
// joining date, a readiness ring on each, documents to check, late tasks and the daily
// reminder check. Full width (16.1); every action is one the existing API supports.
export default function OnboardingDashboardPage() {
  const f = useTheme().palette.fresh;
  const { t, locale } = useI18n();
  const d = useDateText();
  const { can } = useMeBootstrap();
  const [board, setBoard] = useState<OnboardingBoard | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [openCase, setOpenCase] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [link, setLink] = useState<{ token: string; name: string } | null>(null);
  const [dateFor, setDateFor] = useState<JoinerCardData | null>(null);
  const [closeFor, setCloseFor] = useState<{ card: JoinerCardData; kind: "no_show" | "revoke" } | null>(null);
  const [rejecting, setRejecting] = useState<{ id: string; label: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [fileMissing, setFileMissing] = useState(false);

  const canView = can("onboarding.preboarding.view");

  const load = useCallback(() => {
    setError(null);
    onboardingExtraApi.board(locale).then(setBoard).catch(setError);
  }, [locale]);

  useEffect(() => {
    if (canView) load();
  }, [canView, load]);

  const grouped = useMemo(() => {
    const out: Record<JoinGroup, JoinerCardData[]> = { passed: [], this_week: [], next_week: [], later: [] };
    for (const c of board?.cards ?? []) out[joinGroup(c.days_to_join)].push(c);
    return out;
  }, [board]);

  const perm = board?.can ?? { create: false, edit: false, approve: false, tasks: false, plans: false };

  const act = async (key: string, fn: () => Promise<unknown>, done?: string) => {
    setBusy(key);
    setActionError(null);
    try {
      await fn();
      if (done) setToast(done);
      load();
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(null);
    }
  };

  const onAction = (action: JoinerAction, card: JoinerCardData) => {
    switch (action) {
      case "open": setOpenCase(card.case_id); break;
      case "date": setDateFor(card); break;
      case "no_show": setCloseFor({ card, kind: "no_show" }); break;
      case "revoke": setCloseFor({ card, kind: "revoke" }); break;
      case "link":
        void act(`link:${card.case_id}`, async () => {
          const res = await onboardingExtraApi.rotateLink(card.case_id);
          setLink({ token: res.portal_token, name: card.name });
        });
        break;
      case "joined":
        void act(`joined:${card.case_id}`, async () => {
          const res = await onboardingExtraApi.convert(card.case_id);
          void celebrate(`joiner.joined:${card.case_id}`);
          setToast(t("onboarding.toast.joined", { name: card.name, code: res.employee_code }));
        });
        break;
    }
  };

  if (!canView) {
    return (
      <Box>
        <PageHeader emoji="waving_hand" title={t("onboarding.title")} purpose={t("onboarding.purpose")} />
        <FriendlyError what={t("onboarding.no_access")} fix={t("onboarding.no_access_fix")} actionLabel={t("action.go_home")} actionTo="/" />
      </Box>
    );
  }

  const cards = board?.cards ?? [];
  const notReady = cards.filter((c) => c.not_ready_soon).length;
  const thisMonth = cards.filter((c) => c.joining_date.slice(0, 7) === (board?.today ?? "").slice(0, 7)).length;
  const avgReady = cards.length ? Math.round(cards.reduce((s, c) => s + c.readiness_percent, 0) / cards.length) : 0;

  const primary = perm.create ? (
    <Button variant="contained" onClick={() => setStarting(true)}><Emoji name="waving_hand" size={18} />&nbsp;{t("onboarding.start.button")}</Button>
  ) : undefined;

  const digest = board?.digest;
  const digestLine = !digest ? null
    : !digest.enabled ? t("onboarding.digest.off")
      : digest.last_found_at ? t("onboarding.digest.last", { when: d.when(digest.last_found_at), count: digest.reminders_waiting })
        : t("onboarding.digest.on_nothing");

  return (
    <Box>
      <PageHeader
        emoji="waving_hand" title={t("onboarding.title")} purpose={t("onboarding.purpose")} primary={primary} tourKey="onboarding"
        below={digestLine ? (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ color: f.muted, fontSize: 13 }}>
            <Emoji name={digest?.enabled ? "bell" : "pause"} size={16} />
            <Typography component="span" sx={{ fontSize: 13 }}>{digestLine}</Typography>
            <InfoTip text={t("onboarding.digest.tip")} />
          </Stack>
        ) : undefined}
      />

      {error ? <FriendlyError error={error} onRetry={load} />
        : (
          <Stack spacing={2.5}>
            <PageGrid>
              <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="waving_hand" value={cards.length} label={t("onboarding.stat.joining", { count: cards.length })} loading={!board} tone="brand" /></Cell>
              <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="party" value={thisMonth} label={t("onboarding.stat.this_month", { count: thisMonth })} loading={!board} tone="sun" /></Cell>
              <Cell span={{ xs: 6, md: 3 }}>
                <StatTile emoji="warning" value={notReady} label={t("onboarding.stat.not_ready", { count: notReady })} loading={!board} tone="coral"
                  trend={notReady ? t("onboarding.stat.not_ready_trend") : t("onboarding.stat.all_good")} trendDirection={notReady ? "down" : "up"} />
              </Cell>
              <Cell span={{ xs: 6, md: 3 }}>
                <StatTile emoji="page" value={board?.documents_waiting.length ?? 0} label={t("onboarding.stat.docs", { count: board?.documents_waiting.length ?? 0 })} loading={!board} tone="sky"
                  trend={cards.length ? t("onboarding.stat.avg_ready", { percent: avgReady }) : undefined} trendDirection="flat" />
              </Cell>
            </PageGrid>

            {actionError ? <FriendlyError error={actionError} compact /> : null}
            {fileMissing && <FriendlyError what={t("onboarding.docs.file_missing")} fix={t("onboarding.docs.file_missing_fix")} compact />}

            {!board ? (
              <PageGrid>
                {[0, 1, 2, 3].map((i) => <Cell key={i} span={{ xs: 12, sm: 6, lg: 4, xl: 3 }}><Skeleton variant="rounded" height={220} sx={{ borderRadius: "18px" }} /></Cell>)}
              </PageGrid>
            ) : cards.length === 0 ? (
              <Card sx={{ p: 2 }}>
                <EmptyState
                  illustration="welcome-aboard" title={t("onboarding.empty.title")} hint={t("onboarding.empty.hint")}
                  action={perm.create ? <Button variant="contained" onClick={() => setStarting(true)}>{t("onboarding.start.button")}</Button> : undefined}
                />
              </Card>
            ) : (
              GROUPS.filter((g) => grouped[g.key].length > 0).map((g) => (
                <Box key={g.key} component="section" aria-labelledby={`grp-${g.key}`}>
                  <Typography id={`grp-${g.key}`} component="h2" sx={{ fontWeight: 800, fontSize: 17, mb: 1.25, display: "flex", alignItems: "center", gap: 1 }}>
                    <Emoji name={g.emoji} size={20} /> {t(`onboarding.group.${g.key}`)}
                    <Typography component="span" sx={{ color: f.muted, fontWeight: 500, fontSize: 13 }}>{t("onboarding.group.count", { count: grouped[g.key].length })}</Typography>
                  </Typography>
                  <PageGrid>
                    {grouped[g.key].map((c) => (
                      <Cell key={c.case_id} span={{ xs: 12, sm: 6, lg: 4, xl: 3 }}>
                        <JoinerCard card={c} canEdit={perm.edit} canApprove={perm.approve} onAction={onAction} busy={busy === `joined:${c.case_id}`} />
                      </Cell>
                    ))}
                  </PageGrid>
                </Box>
              ))
            )}

            {board && (
              <PageGrid>
                <Cell span={{ xs: 12, lg: 7 }}>
                  <Card sx={{ p: 2.25 }}>
                    <Typography component="h2" sx={{ fontWeight: 700, fontSize: 16, mb: 1.5 }}>
                      <Emoji name="page" /> {t("onboarding.docs.title")}
                      <Typography component="span" sx={{ color: f.muted, fontSize: 12, ml: 1 }}>{t("onboarding.docs.sub")}</Typography>
                    </Typography>
                    {board.documents_waiting.length === 0 ? (
                      <EmptyState compact illustration="completed-steps" title={t("onboarding.docs.none")} />
                    ) : (
                      <Stack component="ul" spacing={1} sx={{ listStyle: "none", p: 0, m: 0 }}>
                        {board.documents_waiting.map((doc) => (
                          <Stack component="li" key={doc.id} direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }} sx={{ p: 1.25, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                            <Stack direction="row" spacing={1.5} alignItems="center" sx={{ flex: 1, minWidth: 0 }}>
                              <UserAvatar name={doc.name} size={34} />
                              <Box sx={{ minWidth: 0 }}>
                                <Typography sx={{ fontWeight: 600 }} noWrap>{doc.label} · {doc.name}</Typography>
                                <Typography sx={{ fontSize: 12, color: f.muted }}>{doc.uploaded_at ? t("onboarding.docs.uploaded_at", { when: d.when(doc.uploaded_at) }) : ""}</Typography>
                              </Box>
                            </Stack>
                            <Stack direction="row" spacing={1}>
                              <Button size="small" variant="outlined" onClick={async () => { setFileMissing(!(await openDocument(doc.id))); }}>{t("onboarding.docs.view")}</Button>
                              {perm.edit && (
                                <>
                                  <Button size="small" variant="contained" disabled={busy === doc.id} onClick={() => act(doc.id, () => onboardingExtraApi.verifyDocument(doc.id, true), t("onboarding.toast.approved", { label: doc.label }))}>{t("onboarding.docs.approve")}</Button>
                                  <Button size="small" color="error" onClick={() => setRejecting({ id: doc.id, label: doc.label })}>{t("onboarding.docs.reject")}</Button>
                                </>
                              )}
                            </Stack>
                          </Stack>
                        ))}
                      </Stack>
                    )}
                  </Card>
                </Cell>
                <Cell span={{ xs: 12, lg: 5 }}>
                  <Card sx={{ p: 2.25 }}>
                    <Typography component="h2" sx={{ fontWeight: 700, fontSize: 16, mb: 1.5 }}>
                      <Emoji name="fire" /> {t("onboarding.overdue.title")}
                      <Typography component="span" sx={{ color: f.muted, fontSize: 12, ml: 1 }}>{t("onboarding.overdue.sub")}</Typography>
                    </Typography>
                    {board.overdue_tasks.length === 0 ? (
                      <EmptyState compact illustration="done" title={t("onboarding.overdue.none")} />
                    ) : (
                      <Stack component="ul" spacing={1} sx={{ listStyle: "none", p: 0, m: 0 }}>
                        {board.overdue_tasks.map((task) => (
                          <Stack component="li" key={task.id} direction="row" spacing={1.5} alignItems="center" sx={{ p: 1.25, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                            <Box sx={{ flex: 1, minWidth: 0 }}>
                              <Typography sx={{ fontWeight: 600 }}>{task.title}</Typography>
                              <Typography sx={{ fontSize: 12, color: f.muted }}>{[task.name, ownerText(task.owner_role, t)].filter(Boolean).join(" · ")}</Typography>
                            </Box>
                            <StatusChip tone="coral" emoji="fire" label={t("onboarding.overdue.days_late", { count: task.days_late })} />
                            {perm.tasks && task.status === "pending" && (
                              <Button size="small" variant="outlined" disabled={busy === task.id} onClick={() => act(task.id, () => onboardingExtraApi.completeTask(task.id), t("onboarding.toast.task_done"))}>{t("onboarding.tasks.mark_done")}</Button>
                            )}
                          </Stack>
                        ))}
                      </Stack>
                    )}
                  </Card>
                </Cell>
              </PageGrid>
            )}
          </Stack>
        )}

      <JoinerDrawer caseId={openCase} onClose={() => setOpenCase(null)} onChanged={load} canEdit={perm.edit} canTasks={perm.tasks} canPlans={perm.plans} />
      <StartDialog
        open={starting} offers={board?.ready_offers ?? []} onClose={() => setStarting(false)}
        onCreated={(token, name) => { setStarting(false); setLink({ token, name }); load(); }}
      />
      <LinkDialog token={link?.token ?? null} name={link?.name ?? ""} onClose={() => setLink(null)} />
      <DateDialog
        open={Boolean(dateFor)} name={dateFor?.name ?? ""} current={dateFor?.joining_date ?? ""} onClose={() => setDateFor(null)}
        onSave={async (date, reason) => {
          if (!dateFor) return;
          await onboardingExtraApi.changeJoiningDate(dateFor.case_id, date, reason || undefined);
          setToast(t("onboarding.toast.date", { name: dateFor.name, date: d.day(date) }));
          setDateFor(null);
          load();
        }}
      />
      <CloseDialog
        kind={closeFor?.kind ?? null} name={closeFor?.card.name ?? ""} onClose={() => setCloseFor(null)}
        onConfirm={async (reason) => {
          if (!closeFor) return;
          const { card, kind } = closeFor;
          if (kind === "revoke") await onboardingExtraApi.revoke(card.case_id, reason || undefined);
          else await onboardingExtraApi.noShow(card.case_id, reason || undefined);
          setToast(t(kind === "revoke" ? "onboarding.toast.revoked" : "onboarding.toast.no_show", { name: card.name }));
          setCloseFor(null);
          load();
        }}
      />
      <RejectDialog
        label={rejecting?.label ?? null} onClose={() => setRejecting(null)}
        onConfirm={async (reason) => {
          if (!rejecting) return;
          await onboardingExtraApi.verifyDocument(rejecting.id, false, reason);
          setToast(t("onboarding.toast.sent_back", { label: rejecting.label }));
          setRejecting(null);
          load();
        }}
      />
      <Snackbar open={Boolean(toast)} autoHideDuration={5000} onClose={() => setToast(null)}>
        <Alert severity="success" onClose={() => setToast(null)} variant="filled">{toast}</Alert>
      </Snackbar>
    </Box>
  );
}
