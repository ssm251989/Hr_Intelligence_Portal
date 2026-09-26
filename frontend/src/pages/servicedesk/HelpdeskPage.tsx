// Part 15.6 -- /helpdesk (L T1, T3, T4). Employee: raise a ticket (topic FIRST, then the
// summary; a help-article answer is offered before sending -> "This solved it" records a
// deflection), my tickets with the response-time chip, one-click rating once fixed.
import { useCallback, useEffect, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonBase from "@mui/material/ButtonBase";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { serviceDeskExtra, type KbHit, type Ticket, type TicketMeta } from "../../api/serviceDeskExtra";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import RateTicket from "../../components/servicedesk/RateTicket";
import TicketDetailDialog from "../../components/servicedesk/TicketDetailDialog";
import { EscalationChip, Section, TicketClockChip, TicketStatusChip, useCategories, useDateFmt, useNow, useToast } from "../../components/servicedesk/shared";
import { useT } from "../../i18n";
import { Cell, EmptyState, Emoji, FriendlyAnimation, FriendlyError, InfoTip, PageGrid, PageHeader, useReducedMotion } from "../../ui-kit";

const PRIORITIES = ["low", "medium", "high", "urgent"];
const CATEGORY_EMOJI: Record<string, string> = { it: "laptop", hr: "people", payroll: "money", admin: "building", facilities: "building", finance: "bank", leave: "calendar", access: "key" };

function RaiseTicket({ onSent }: { onSent: (ticket: Ticket) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const reduced = useReducedMotion();
  const cats = useCategories("ticket");
  const [category, setCategory] = useState<string | null>(null);
  const [subject, setSubject] = useState("");
  const [details, setDetails] = useState("");
  const [priority, setPriority] = useState("medium");
  const [hits, setHits] = useState<KbHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [solved, setSolved] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const subjectRef = useRef<HTMLInputElement>(null);

  // AI / help-article answer BEFORE submit: search as the person types the summary.
  useEffect(() => {
    const q = `${subject} ${details}`.trim();
    if (q.length < 4) {
      setHits(null);
      return;
    }
    setSearching(true);
    const id = window.setTimeout(() => {
      serviceDeskExtra.kbSearch(q).then(setHits).catch(() => setHits([])).finally(() => setSearching(false));
    }, 450);
    return () => window.clearTimeout(id);
  }, [subject, details]);

  useEffect(() => {
    if (category) subjectRef.current?.focus();
  }, [category]);

  const reset = () => {
    setCategory(null);
    setSubject("");
    setDetails("");
    setPriority("medium");
    setHits(null);
    setDismissed(new Set());
    setSolved(false);
  };

  const deflect = async (hit: KbHit, helpful: boolean) => {
    serviceDeskExtra.kbDeflected(hit.id, helpful).catch(() => undefined);
    if (helpful) setSolved(true);
    else setDismissed((s) => new Set(s).add(hit.id));
  };

  const submit = async () => {
    if (!category || !subject.trim()) return;
    setSending(true);
    setError(null);
    try {
      const ticket = await serviceDeskExtra.raiseTicket({ category_code: category, subject: subject.trim(), description: details.trim() || undefined, priority });
      reset();
      onSent(ticket);
    } catch (e) {
      setError(e);
    } finally {
      setSending(false);
    }
  };

  if (solved) {
    return (
      <Stack alignItems="center" spacing={1.5} sx={{ py: 3, textAlign: "center" }} role="status">
        {!reduced ? <FriendlyAnimation name="success" size={96} /> : <Emoji name="party" size={48} />}
        <Typography sx={{ fontWeight: 800 }}>{t("helpdesk.suggest.thanks")}</Typography>
        <Button variant="outlined" onClick={reset}>{t("helpdesk.primary")}</Button>
      </Stack>
    );
  }

  if (cats.error) return <FriendlyError error={cats.error} onRetry={cats.reload} compact />;
  if (cats.list === null) return <Box sx={{ display: "grid", placeItems: "center", py: 4 }}><CircularProgress aria-label={t("helpdesk.common.loading")} /></Box>;
  if (cats.list.length === 0) return <EmptyState compact illustration="empty" title={t("helpdesk.raise.no_categories")} />;

  const visibleHits = (hits ?? []).filter((h) => !dismissed.has(h.id));

  return (
    <Stack spacing={2}>
      {/* Step 1: category first */}
      <Box>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
          <Typography component="h3" sx={{ fontWeight: 800 }}>{t("helpdesk.raise.step1")}</Typography>
          {category && <Button size="small" onClick={() => setCategory(null)}>{t("helpdesk.raise.change")}</Button>}
        </Stack>
        <Typography sx={{ color: f.muted, fontSize: 14, mb: 1 }}>{t("helpdesk.raise.step1_hint")}</Typography>
        <Box role="radiogroup" aria-label={t("helpdesk.raise.step1")}
          sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 1 }}>
          {cats.list.filter((c) => !category || c.code === category).map((c) => {
            const selected = c.code === category;
            return (
              <ButtonBase key={c.code} role="radio" aria-checked={selected} onClick={() => setCategory(c.code)}
                sx={{ justifyContent: "flex-start", gap: 1, p: 1.5, borderRadius: "12px", textAlign: "left",
                  border: `2px solid ${selected ? f.brand : f.line}`, bgcolor: selected ? f.brandSoft : f.surface,
                  "&:hover, &:focus-visible": { borderColor: f.brand } }}>
                <Emoji name={c.emoji || CATEGORY_EMOJI[c.code] || "question"} size={22} />
                <Box sx={{ minWidth: 0 }}>
                  <Typography sx={{ fontWeight: 700, fontSize: 14 }}>{c.label}</Typography>
                  {c.hint && <Typography sx={{ fontSize: 12, color: f.muted }}>{c.hint}</Typography>}
                </Box>
              </ButtonBase>
            );
          })}
        </Box>
      </Box>

      {/* Step 2: subject / details -- only after a topic is picked */}
      {category && (
        <Box>
          <Typography component="h3" sx={{ fontWeight: 800, mb: 1 }}>{t("helpdesk.raise.step2")}</Typography>
          <Stack spacing={1.5}>
            <TextField inputRef={subjectRef} required label={t("helpdesk.field.subject")} placeholder={t("helpdesk.field.subject_ph")} helperText={t("helpdesk.field.subject_hint")}
              value={subject} onChange={(e) => setSubject(e.target.value)} fullWidth inputProps={{ maxLength: 200 }} />
            <TextField label={t("helpdesk.field.details")} placeholder={t("helpdesk.field.details_ph")} helperText={t("helpdesk.field.details_hint")}
              value={details} onChange={(e) => setDetails(e.target.value)} fullWidth multiline minRows={3} />
            <Stack direction="row" alignItems="center">
              <TextField select label={t("helpdesk.field.priority")} value={priority} onChange={(e) => setPriority(e.target.value)} sx={{ minWidth: 240 }}>
                {PRIORITIES.map((p) => <MenuItem key={p} value={p}>{t(`helpdesk.priority.${p}`)}</MenuItem>)}
              </TextField>
              <InfoTip text={t("helpdesk.field.priority_tip")} />
            </Stack>
          </Stack>

          {/* Suggested answer before submit */}
          {(searching || hits !== null) && (
            <Card aria-live="polite" sx={{ mt: 2, p: 2, bgcolor: f.skySoft, boxShadow: "none" }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                <Emoji name="light_bulb" size={18} />
                <Typography sx={{ fontWeight: 800 }}>{t("helpdesk.suggest.title")}</Typography>
              </Stack>
              {searching ? (
                <Typography sx={{ fontSize: 14, color: f.muted }}>{t("helpdesk.suggest.searching")}</Typography>
              ) : visibleHits.length === 0 ? (
                <Typography sx={{ fontSize: 14, color: f.muted }}>{t("helpdesk.suggest.none")}</Typography>
              ) : (
                <>
                  <Typography sx={{ fontSize: 13, color: f.muted, mb: 1 }}>{t("helpdesk.suggest.hint")}</Typography>
                  <Stack spacing={1}>
                    {visibleHits.slice(0, 3).map((h) => (
                      <Box key={h.id} sx={{ bgcolor: f.surface, borderRadius: "12px", p: 1.5 }}>
                        <Typography sx={{ fontWeight: 700 }}>{h.title}</Typography>
                        <Typography sx={{ fontSize: 14, mt: 0.5, whiteSpace: "pre-wrap", maxWidth: "75ch",
                          ...(expanded === h.id ? {} : { display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }) }}>
                          {h.excerpt}
                        </Typography>
                        <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
                          <Button size="small" variant="contained" startIcon={<Emoji name="check" size={14} />} onClick={() => deflect(h, true)}>{t("helpdesk.suggest.solved")}</Button>
                          <Button size="small" variant="outlined" onClick={() => deflect(h, false)}>{t("helpdesk.suggest.not_this")}</Button>
                          <Button size="small" onClick={() => setExpanded(expanded === h.id ? null : h.id)}>
                            {t(expanded === h.id ? "helpdesk.suggest.read_less" : "helpdesk.suggest.read_more")}
                          </Button>
                        </Stack>
                      </Box>
                    ))}
                  </Stack>
                </>
              )}
            </Card>
          )}

          {error ? <Box sx={{ mt: 2 }}><FriendlyError error={error} compact /></Box> : null}
          <Stack direction="row" justifyContent="flex-end" sx={{ mt: 2 }}>
            <Button variant="contained" size="large" onClick={submit} disabled={sending || !subject.trim()} startIcon={<Emoji name="envelope" size={16} />}>
              {sending ? t("helpdesk.submitting") : t("helpdesk.submit")}
            </Button>
          </Stack>
        </Box>
      )}
    </Stack>
  );
}

function MyTickets({ reloadKey, onOpen, categoryLabel }: { reloadKey: number; onOpen: (id: string) => void; categoryLabel: (c?: string | null) => string }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const now = useNow();
  const [rows, setRows] = useState<Ticket[] | null>(null);
  const [meta, setMeta] = useState<Record<string, TicketMeta>>({});
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    setError(null);
    serviceDeskExtra.myTickets().then((list) => {
      setRows(list);
      if (list.length) serviceDeskExtra.ticketsMeta(list.slice(0, 100).map((x) => x.id)).then(setMeta).catch(() => undefined);
    }).catch(setError);
  }, []);
  useEffect(load, [load, reloadKey]);

  if (error) return <FriendlyError error={error} onRetry={load} compact />;
  if (rows === null) return <Box sx={{ display: "grid", placeItems: "center", py: 4 }}><CircularProgress aria-label={t("helpdesk.common.loading")} /></Box>;
  if (rows.length === 0) return <EmptyState compact illustration="empty" title={t("helpdesk.mine.empty")} hint={t("helpdesk.mine.empty_hint")} />;

  return (
    <Stack spacing={1} component="ul" sx={{ listStyle: "none", p: 0, m: 0 }}>
      {rows.map((tk) => (
        <Box component="li" key={tk.id} sx={{ border: `1px solid ${f.line}`, borderRadius: "12px", p: 1.5, bgcolor: f.surface2 }}>
          <Stack direction="row" spacing={1} alignItems="flex-start">
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <ButtonBase onClick={() => onOpen(tk.id)} sx={{ textAlign: "left", display: "block", borderRadius: 1 }}>
                <Typography sx={{ fontWeight: 700 }}>{tk.subject}</Typography>
                <Typography sx={{ fontSize: 12, color: f.muted }}>
                  {tk.number} · {categoryLabel(tk.category_code)} · {fmt.date(tk.created_at)}
                </Typography>
              </ButtonBase>
              <Stack direction="row" spacing={0.75} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
                <TicketStatusChip status={tk.status} forEmployee />
                {!["resolved", "closed", "cancelled"].includes(tk.status) && <TicketClockChip ticket={tk} meta={meta[tk.id]} now={now} />}
                <EscalationChip level={tk.escalation_level} />
              </Stack>
              {["resolved", "closed"].includes(tk.status) && (
                <Box sx={{ mt: 1 }}><RateTicket ticketId={tk.id} score={tk.csat_score} compact /></Box>
              )}
            </Box>
            <Button size="small" onClick={() => onOpen(tk.id)}>{t("helpdesk.common.open")}</Button>
          </Stack>
        </Box>
      ))}
    </Stack>
  );
}

export default function HelpdeskPage() {
  const t = useT();
  const { can } = useMeBootstrap();
  const cats = useCategories("ticket");
  const [toast, show] = useToast();
  const [reloadKey, setReloadKey] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const canRaise = can("helpdesk.self.create");
  const canSeeMine = can("helpdesk.self.view");
  const isAgent = can("helpdesk.ticket.view");
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    if (canSeeMine) serviceDeskExtra.myTickets().then((r) => setCount(r.length)).catch(() => undefined);
  }, [canSeeMine, reloadKey]);

  const focusRaise = () => {
    const el = document.getElementById("sd-raise");
    el?.scrollIntoView({ block: "start" });
    el?.querySelector<HTMLElement>("[role=radio]")?.focus();
  };

  return (
    <Box>
      <PageHeader
        emoji="ring_buoy"
        title={t("helpdesk.title")}
        purpose={t("helpdesk.purpose")}
        tourKey="helpdesk"
        primary={canRaise ? <Button variant="contained" onClick={focusRaise} startIcon={<Emoji name="ring_buoy" size={16} />}>{t("helpdesk.primary")}</Button> : undefined}
        extra={isAgent ? <Button variant="text" component={RouterLink} to="/helpdesk/queue">{t("helpdesk.view_queue")}</Button> : undefined}
      />
      <PageGrid>
        <Cell span={{ md: 12, lg: 7 }}>
          <Section id="sd-raise" emoji="memo" title={t("helpdesk.raise.title")}>
            {canRaise ? (
              <RaiseTicket onSent={(tk) => { show(t("helpdesk.sent", { number: tk.number })); setReloadKey((k) => k + 1); }} />
            ) : (
              <EmptyState compact illustration="empty" title={t("helpdesk.raise.no_access")} />
            )}
          </Section>
        </Cell>
        {canSeeMine && (
          <Cell span={{ md: 12, lg: 5 }}>
            <Section emoji="inbox" title={t("helpdesk.mine.title")}
              action={count !== null ? <Typography sx={{ fontSize: 13, color: "text.secondary" }}>{t("helpdesk.mine.count", { count })}</Typography> : undefined}>
              <MyTickets reloadKey={reloadKey} onOpen={setOpenId} categoryLabel={cats.label} />
            </Section>
          </Cell>
        )}
      </PageGrid>
      <TicketDetailDialog ticketId={openId} open={Boolean(openId)} onClose={() => setOpenId(null)} onChanged={() => setReloadKey((k) => k + 1)} categoryLabel={cats.label} />
      {toast}
    </Box>
  );
}
