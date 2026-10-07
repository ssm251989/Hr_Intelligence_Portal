import { useEffect, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Drawer from "@mui/material/Drawer";
import Fab from "@mui/material/Fab";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import CloseIcon from "@mui/icons-material/Close";
import SendRoundedIcon from "@mui/icons-material/SendRounded";

import { extractErrorMessage, intelligenceApi, type CopilotAnswer } from "../api/client";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";
import { LOCALES, useI18n } from "../i18n";
import { Emoji, FriendlyError, humanise, StatusChip } from "../ui-kit";
import { useReducedMotion } from "../ui-kit/motion";

// Part 12 section B + Part 15.6 R5-R7: the HR assistant, a floating button on every page.
// Rendered only when the company has the `copilot.chat` AI feature on AND the user holds
// copilot.chat.view. Every answer shows the SOURCES it came from; actions come back as
// drafted cards the user must Confirm or Discard -- this widget never submits on its own.

type UUID = string;

interface Turn {
  question: string;
  reply?: CopilotAnswer;
  error?: unknown;
  draft?: { state: "confirmed" | "discarded" | "failed"; text: string };
}

const EXAMPLES = ["assistant.eg1", "assistant.eg2", "assistant.eg3"];
// Part 22.1: shown when a question is unclear ("Eg1")
const SUGGESTIONS = ["assistant.sugg.leave", "assistant.sugg.notice", "assistant.sugg.salary", "assistant.sugg.jobs"];

function friendlyValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.map(friendlyValue).join(", ");
  if (typeof v === "object") return Object.values(v as Record<string, unknown>).map(friendlyValue).join(", ");
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) {
    const d = new Date(v);
    if (!Number.isNaN(d.getTime())) return d.toLocaleDateString();
  }
  return String(v);
}

export default function CopilotWidget() {
  const { can, aiFeature } = useMeBootstrap();
  const { t, locale } = useI18n();
  const f = useTheme().palette.fresh;
  const reduced = useReducedMotion();
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [language, setLanguage] = useState<string>(locale);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversationId, setConversationId] = useState<UUID | undefined>();
  const [busy, setBusy] = useState(false);
  const [categoryOf, setCategoryOf] = useState<Record<string, string>>({});  // Part 22.1: the ticket category, editable
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => setLanguage(locale), [locale]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "end" });
  }, [turns, busy, reduced]);

  if (!aiFeature("copilot.chat") || !can("copilot.chat.view")) return null;

  const setTurn = (index: number, patch: Partial<Turn>) => setTurns((prev) => prev.map((x, i) => (i === index ? { ...x, ...patch } : x)));

  const ask = (text?: string) => {
    const q = (text ?? question).trim();
    if (!q || busy) return;
    setBusy(true);
    setQuestion("");
    const index = turns.length;
    setTurns((prev) => [...prev, { question: q }]);
    intelligenceApi
      .ask(q, language, conversationId)
      .then((reply) => {
        setConversationId(reply.conversation_id);
        setTurn(index, { reply });
      })
      .catch((error) => setTurn(index, { error }))
      .finally(() => setBusy(false));
  };

  const confirm = (index: number, draftId: UUID) =>
    intelligenceApi
      .confirmDraft(draftId, categoryOf[draftId] ? { category_code: categoryOf[draftId] } : {})
      .then((r) =>
        setTurn(index, r.status === "confirmed"
          ? { draft: { state: "confirmed", text: r.result?.startsWith("hr_todo:") ? t("assistant.sent_hr") : r.result ? t("assistant.done_ref", { ref: r.result }) : t("assistant.done") } }
          : { draft: { state: "failed", text: r.error || t("assistant.failed") } }))
      // fix 22.1: show the server's reason, not just "Something went wrong."
      .catch((err) => setTurn(index, { draft: { state: "failed", text: extractErrorMessage(err, t("assistant.failed")) } }));

  const discard = (index: number, draftId: UUID) =>
    intelligenceApi
      .discardDraft(draftId)
      .then(() => setTurn(index, { draft: { state: "discarded", text: t("assistant.discarded") } }))
      .catch(() => setTurn(index, { draft: { state: "failed", text: t("assistant.failed") } }));

  const actionName = (action: string) => {
    const key = `assistant.action.${action}`;
    const tr = t(key);
    return tr !== key ? tr : humanise(action.split(".").slice(-2).join(" "));
  };

  const bubble = { px: 1.75, py: 1.25, borderRadius: "16px", maxWidth: "88%", whiteSpace: "pre-wrap" as const, wordBreak: "break-word" as const };

  return (
    <>
      {/* fix 2026-10-05: hidden while the panel is open -- it sat on top of the panel's Send button */}
      {!open && (
        <Tooltip title={t("assistant.open")} placement="left">
          <Fab color="primary" aria-label={t("assistant.open")} onClick={() => setOpen(true)}
            sx={{ position: "fixed", bottom: 24, right: 24, zIndex: (th) => th.zIndex.drawer + 1, boxShadow: f.shadowHover }}>
            <Emoji name="robot" size={28} />
          </Fab>
        </Tooltip>
      )}
      <Drawer anchor="right" open={open} onClose={() => setOpen(false)}
        slotProps={{ paper: { sx: { width: { xs: "100%", sm: 440 }, display: "flex", flexDirection: "column", bgcolor: f.ground } } }}>
        <Stack direction="row" alignItems="center" spacing={1.5} sx={{ px: 2, py: 1.75, bgcolor: f.surface, borderBottom: `1px solid ${f.line}` }}>
          <Box sx={{ width: 40, height: 40, borderRadius: "12px", bgcolor: f.brandSoft, display: "grid", placeItems: "center" }}>
            <Emoji name="robot" size={24} />
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography component="h2" sx={{ fontWeight: 800, fontSize: 17 }}>{t("assistant.title")}</Typography>
            <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("assistant.subtitle")}</Typography>
          </Box>
          <IconButton aria-label={t("assistant.close")} onClick={() => setOpen(false)}>
            <CloseIcon />
          </IconButton>
        </Stack>

        <Box sx={{ flex: 1, overflowY: "auto", p: 2 }} aria-live="polite">
          {turns.length === 0 && (
            <Box sx={{ textAlign: "center", pt: 3 }}>
              <Emoji name="waving_hand" size={40} />
              <Typography sx={{ fontWeight: 800, mt: 1 }}>{t("assistant.hello")}</Typography>
              <Typography sx={{ color: f.muted, mt: 0.5, mb: 2 }}>{t("assistant.intro")}</Typography>
              <Stack spacing={1} alignItems="stretch">
                {EXAMPLES.map((k) => (
                  <Button key={k} variant="outlined" onClick={() => ask(t(k))} sx={{ justifyContent: "flex-start", textAlign: "left", bgcolor: f.surface }}
                    startIcon={<Emoji name="speech" size={16} />}>
                    {t(k)}
                  </Button>
                ))}
              </Stack>
            </Box>
          )}

          {turns.map((turn, i) => (
            <Stack key={i} spacing={1} sx={{ mb: 2.5 }}>
              <Box sx={{ ...bubble, alignSelf: "flex-end", bgcolor: f.brand, color: f.brandInk, borderBottomRightRadius: "4px" }}>
                <Typography sx={{ fontSize: 14 }}>{turn.question}</Typography>
              </Box>
              {turn.error !== undefined && <FriendlyError error={turn.error} compact />}
              {!turn.reply && turn.error === undefined && (
                <Box sx={{ ...bubble, alignSelf: "flex-start", bgcolor: f.surface, border: `1px solid ${f.line}` }}>
                  <Typography sx={{ color: f.muted, fontSize: 14 }}>{t("assistant.thinking")}</Typography>
                </Box>
              )}
              {turn.reply && (
                <Box sx={{ ...bubble, alignSelf: "flex-start", bgcolor: f.surface, border: `1px solid ${f.line}`, borderBottomLeftRadius: "4px" }}>
                  <Typography sx={{ fontSize: 14 }}>{turn.reply.answer}</Typography>
                  {turn.reply.handover && (
                    <Box sx={{ mt: 1 }}><StatusChip tone="sky" emoji="people" label={t("assistant.handover")} /></Box>
                  )}
                  {turn.reply.clarify && (
                    <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
                      {SUGGESTIONS.map((k) => (
                        <Chip key={k} size="small" variant="outlined" clickable label={t(k)} onClick={() => ask(t(k))} />
                      ))}
                    </Stack>
                  )}

                  {!turn.reply.clarify && <Box sx={{ mt: 1.25, pt: 1, borderTop: `1px dashed ${f.line}` }}>
                    <Typography sx={{ fontSize: 12, fontWeight: 800, color: f.muted, mb: 0.5, display: "flex", alignItems: "center", gap: 0.5 }}>
                      <Emoji name="page" size={14} /> {t("assistant.sources")}
                    </Typography>
                    {turn.reply.citations.length === 0 ? (
                      <Typography sx={{ fontSize: 12, color: f.muted }}>{t("assistant.no_sources")}</Typography>
                    ) : (
                      <Stack spacing={0.75}>
                        {turn.reply.citations.map((c) => (
                          <Box key={c.n} sx={{ p: "6px 10px", borderRadius: "10px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                            <Typography sx={{ fontSize: 12, fontWeight: 700 }}>[{c.n}] {c.title}{c.heading ? ` - ${c.heading}` : ""}</Typography>
                            {c.excerpt && <Typography sx={{ fontSize: 12, color: f.muted, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{c.excerpt}</Typography>}
                          </Box>
                        ))}
                      </Stack>
                    )}
                  </Box>}

                  {turn.reply.draft && (
                    <Box sx={{ mt: 1.5, p: 1.5, borderRadius: "14px", bgcolor: f.sunSoft, border: `1px solid ${f.line}` }} role="group" aria-label={t("assistant.draft_title")}>
                      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.75 }}>
                        <Emoji name="memo" size={18} />
                        <Typography sx={{ fontWeight: 800, fontSize: 14, flex: 1 }}>{actionName(turn.reply.draft.action)}</Typography>
                        {turn.draft ? (
                          <StatusChip status={turn.draft.state === "confirmed" ? "done" : turn.draft.state === "discarded" ? "cancelled" : "failed"} label={turn.draft.text} />
                        ) : (
                          <StatusChip tone="sun" emoji="hourglass" label={t("assistant.needs_ok")} />
                        )}
                      </Stack>
                      <Box component="dl" sx={{ m: 0, display: "grid", gridTemplateColumns: "auto 1fr", columnGap: 1.5, rowGap: 0.25, fontSize: 13 }}>
                        {Object.entries(turn.reply.draft.payload).filter(([k]) => !/(^|_)id$/.test(k) && k !== "category_code").map(([k, v]) => (
                          <Box key={k} sx={{ display: "contents" }}>
                            <Box component="dt" sx={{ color: f.muted }}>{humanise(k)}</Box>
                            <Box component="dd" sx={{ m: 0, fontWeight: 600 }}>{friendlyValue(v)}</Box>
                          </Box>
                        ))}
                      </Box>
                      {!turn.draft && (turn.reply.draft.categories?.length ?? 0) > 0 && (
                        <TextField select size="small" fullWidth sx={{ mt: 1 }} label={t("assistant.category")}
                          value={categoryOf[turn.reply.draft.id] ?? String(turn.reply.draft.payload.category_code ?? "")}
                          onChange={(e) => { const id = turn.reply!.draft!.id; setCategoryOf((m) => ({ ...m, [id]: e.target.value })); }}>
                          {turn.reply.draft.categories!.map((c) => <MenuItem key={c.code} value={c.code}>{c.name}</MenuItem>)}
                        </TextField>
                      )}
                      {!turn.draft && (
                        <>
                          <Typography sx={{ fontSize: 12, color: f.muted, mt: 1 }}>{t("assistant.draft_hint")}</Typography>
                          <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                            <Button size="small" variant="contained" onClick={() => confirm(i, turn.reply!.draft!.id)} startIcon={<Emoji name="check" size={14} />}>{t("assistant.confirm")}</Button>
                            <Button size="small" variant="outlined" onClick={() => discard(i, turn.reply!.draft!.id)}>{t("assistant.discard")}</Button>
                          </Stack>
                        </>
                      )}
                    </Box>
                  )}
                </Box>
              )}
            </Stack>
          ))}
          <div ref={endRef} />
        </Box>

        <Box component="form" onSubmit={(e) => { e.preventDefault(); ask(); }} sx={{ p: 1.5, bgcolor: f.surface, borderTop: `1px solid ${f.line}` }}>
          <Stack direction="row" spacing={1} alignItems="flex-end">
            <TextField
              size="small" fullWidth multiline maxRows={4}
              placeholder={t("assistant.placeholder")}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask();
                }
              }}
              slotProps={{ htmlInput: { "aria-label": t("assistant.question_label") } }}
            />
            <IconButton type="submit" color="primary" aria-label={t("assistant.send")} disabled={busy || !question.trim()}
              sx={{ bgcolor: f.brandSoft, borderRadius: "11px" }}>
              <SendRoundedIcon />
            </IconButton>
          </Stack>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
            <Typography sx={{ fontSize: 12, color: f.muted }}>{t("assistant.answer_in")}</Typography>
            <TextField select size="small" variant="standard" value={language} onChange={(e) => setLanguage(e.target.value)}
              slotProps={{ htmlInput: { "aria-label": t("assistant.answer_in") } }} sx={{ minWidth: 90 }}>
              {LOCALES.map((l) => <MenuItem key={l.code} value={l.code}>{l.label}</MenuItem>)}
            </TextField>
            <Typography sx={{ fontSize: 12, color: f.muted, ml: "auto !important" }}>{t("assistant.enter_hint")}</Typography>
          </Stack>
        </Box>
      </Drawer>
    </>
  );
}
