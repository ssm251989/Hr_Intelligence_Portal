import { useEffect, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { applicationsApi } from "../../api/client";
import { inboxExtraApi, type ReplySnippet, type ThreadMessage } from "../../api/interviewsExtra";
import type { HrInboundEmailRead } from "../../api/types";
import { useI18n } from "../../i18n";
import { localeTag } from "../interviews/weekDates";
import Emoji from "../../ui-kit/Emoji";
import FriendlyError from "../../ui-kit/FriendlyError";
import InfoTip from "../../ui-kit/InfoTip";
import StatusChip from "../../ui-kit/StatusChip";
import UserAvatar from "../../ui-kit/UserAvatar";

// Middle pane (spec H1): the selected mail plus the sender's other mail, oldest first, and a
// reply box (sent from the shared HR mailbox via POST /applications/{id}/message) with
// insertable snippets taken from the company's published email templates (spec H4).
// `focusReply`: bump it (e.g. the card's "Reply" button) to scroll to the reply box and focus it.
export default function InboxThreadPane({ email, onLinkedChanged, focusReply = 0 }: { email: HrInboundEmailRead; onLinkedChanged?: () => void; focusReply?: number }) {
  const f = useTheme().palette.fresh;
  const { t, locale } = useI18n();
  const fmt = new Intl.DateTimeFormat(localeTag(locale), { dateStyle: "medium", timeStyle: "short" });
  const [messages, setMessages] = useState<ThreadMessage[]>([email]);
  const [snippets, setSnippets] = useState<ReplySnippet[]>([]);
  const [snippetAnchor, setSnippetAnchor] = useState<HTMLElement | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<unknown>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const replyRef = useRef<HTMLElement | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!focusReply) return;
    const handle = setTimeout(() => {
      replyRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      bodyRef.current?.focus({ preventScroll: true });
    }, 50);
    return () => clearTimeout(handle);
  }, [focusReply, email.id]);

  useEffect(() => {
    let alive = true;
    setMessages([email]);
    setSubject(email.subject ? (email.subject.toLowerCase().startsWith("re:") ? email.subject : `Re: ${email.subject}`) : "");
    setBody("");
    setSendError(null);
    setSentTo(null);
    inboxExtraApi
      .thread(email.id)
      .then((r) => alive && r.messages.length > 0 && setMessages(r.messages))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [email]);

  useEffect(() => {
    inboxExtraApi.snippets().then(setSnippets).catch(() => setSnippets([]));
  }, []);

  const applicationId = email.matched_application_id;

  const send = () => {
    if (!applicationId || !body.trim()) return;
    setSending(true);
    setSendError(null);
    applicationsApi
      .message(applicationId, { subject: subject || t("inbox.reply.default_subject"), body })
      .then((r) => {
        setSentTo(r.to);
        setBody("");
        onLinkedChanged?.();
      })
      .catch(setSendError)
      .finally(() => setSending(false));
  };

  const insert = (s: ReplySnippet) => {
    setBody((b) => (b ? `${b}\n\n${s.text}` : s.text));
    if (!subject && s.subject) setSubject(s.subject);
    setSnippetAnchor(null);
  };

  return (
    <Stack spacing={2} sx={{ minWidth: 0 }}>
      <Box>
        <Typography component="h2" sx={{ fontWeight: 800, fontSize: 18, wordBreak: "break-word" }}>
          {email.subject || t("inbox.no_subject")}
        </Typography>
        <Typography sx={{ color: f.muted, fontSize: 13 }}>
          {messages.length === 1 ? t("inbox.thread.count_one") : t("inbox.thread.count", { count: messages.length })}
        </Typography>
      </Box>

      <Stack spacing={1.5} component="ol" sx={{ listStyle: "none", m: 0, p: 0 }} aria-label={t("inbox.thread.label")}>
        {messages.map((m) => {
          const selected = m.id === email.id;
          const when = m.received_at || m.created_at;
          return (
            <Box component="li" key={m.id} sx={{ p: 1.75, borderRadius: "14px", border: `1px solid ${selected ? f.brand : f.line}`, bgcolor: selected ? f.surface : f.surface2 }}>
              <Stack direction="row" spacing={1.25} alignItems="center" justifyContent="space-between" flexWrap="wrap" useFlexGap>
                <Stack direction="row" spacing={1.25} alignItems="center" sx={{ minWidth: 0 }}>
                  <UserAvatar name={m.from_address} size={32} />
                  <Box sx={{ minWidth: 0 }}>
                    <Typography sx={{ fontWeight: 700, fontSize: 14, wordBreak: "break-all" }}>{m.from_address}</Typography>
                    {!selected && m.subject && <Typography sx={{ color: f.muted, fontSize: 12 }}>{m.subject}</Typography>}
                  </Box>
                </Stack>
                <Typography sx={{ color: f.muted, fontSize: 12 }}>{when ? fmt.format(new Date(when)) : ""}</Typography>
              </Stack>
              <Typography sx={{ mt: 1.25, fontSize: 14, whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: selected ? "none" : 160, overflow: "hidden" }}>
                {m.body?.trim() || t("inbox.thread.empty_body")}
              </Typography>
            </Box>
          );
        })}
      </Stack>

      {applicationId ? (
        <Box component="section" ref={replyRef} aria-label={t("inbox.reply.title")} sx={{ p: 1.75, borderRadius: "14px", border: `1px solid ${f.line}`, bgcolor: f.surface }}>
          <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" sx={{ mb: 1.5 }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <Emoji name="envelope" size={18} />
              <Typography sx={{ fontWeight: 700 }}>{t("inbox.reply.title")}</Typography>
              <InfoTip text={t("inbox.reply.info")} />
            </Stack>
            {snippets.length > 0 && (
              <>
                <Button size="small" aria-haspopup="menu" onClick={(e) => setSnippetAnchor(e.currentTarget)} startIcon={<Emoji name="clipboard" size={16} />}>
                  {t("inbox.reply.snippets")}
                </Button>
                <Menu anchorEl={snippetAnchor} open={Boolean(snippetAnchor)} onClose={() => setSnippetAnchor(null)}>
                  {snippets.map((s) => (
                    <MenuItem key={`${s.key}-${s.locale}`} onClick={() => insert(s)} sx={{ maxWidth: 360, whiteSpace: "normal" }}>
                      <Box>
                        <Typography sx={{ fontWeight: 600, fontSize: 14 }}>{s.subject || s.key}</Typography>
                        <Typography sx={{ color: f.muted, fontSize: 12 }} noWrap>{s.text.slice(0, 80)}</Typography>
                      </Box>
                    </MenuItem>
                  ))}
                </Menu>
              </>
            )}
          </Stack>
          <Stack spacing={1.5}>
            <TextField size="small" label={t("inbox.reply.subject")} value={subject} onChange={(e) => setSubject(e.target.value)} fullWidth />
            <TextField inputRef={bodyRef} label={t("inbox.reply.body")} value={body} onChange={(e) => setBody(e.target.value)} fullWidth multiline minRows={4} />
            {sendError ? <FriendlyError error={sendError} compact /> : null}
            {sentTo && <StatusChip tone="ok" emoji="check" label={t("inbox.reply.sent", { to: sentTo })} />}
            <Stack direction="row" justifyContent="flex-end">
              <Button variant="contained" onClick={send} disabled={sending || !body.trim()}>
                {sending ? t("inbox.reply.sending") : t("inbox.reply.send")}
              </Button>
            </Stack>
          </Stack>
        </Box>
      ) : (
        <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("inbox.reply.link_first")}</Typography>
      )}
    </Stack>
  );
}
