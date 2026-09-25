import { useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Drawer from "@mui/material/Drawer";
import Fab from "@mui/material/Fab";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import ChatOutlinedIcon from "@mui/icons-material/ChatOutlined";
import CloseIcon from "@mui/icons-material/Close";

import { extractErrorMessage, intelligenceApi, type CopilotAnswer } from "../api/client";

type UUID = string;
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";

// Part 12 section B (docs/HRMS_COMPLETE_SPEC.txt): the HR Copilot web widget. Rendered
// only when the tenant has the `copilot.chat` AI feature on AND the user holds
// copilot.chat.view. Policy answers always show their citations; actions come back as
// drafts the user must confirm -- this widget never submits anything on its own.

interface Turn {
  question: string;
  reply?: CopilotAnswer;
  error?: string;
  draftStatus?: string;
}

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "ta", label: "தமிழ்" },
];

export default function CopilotWidget() {
  const { can, aiFeature } = useMeBootstrap();
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [language, setLanguage] = useState("en");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversationId, setConversationId] = useState<UUID | undefined>();
  const [busy, setBusy] = useState(false);

  if (!aiFeature("copilot.chat") || !can("copilot.chat.view")) return null;

  const ask = () => {
    const q = question.trim();
    if (!q) return;
    setBusy(true);
    setQuestion("");
    const index = turns.length;
    setTurns((prev) => [...prev, { question: q }]);
    intelligenceApi
      .ask(q, language, conversationId)
      .then((reply) => {
        setConversationId(reply.conversation_id);
        setTurns((prev) => prev.map((t, i) => (i === index ? { ...t, reply } : t)));
      })
      .catch((err) => setTurns((prev) => prev.map((t, i) => (i === index ? { ...t, error: extractErrorMessage(err, "Copilot couldn't answer right now") } : t))))
      .finally(() => setBusy(false));
  };

  const confirm = (index: number, draftId: UUID) =>
    intelligenceApi
      .confirmDraft(draftId)
      .then((r) => setTurns((prev) => prev.map((t, i) => (i === index ? { ...t, draftStatus: r.status === "confirmed" ? `Submitted (${r.result})` : r.error || r.status } : t))))
      .catch((err) => setTurns((prev) => prev.map((t, i) => (i === index ? { ...t, draftStatus: extractErrorMessage(err, "Could not submit") } : t))));

  const discard = (index: number, draftId: UUID) =>
    intelligenceApi.discardDraft(draftId).then(() => setTurns((prev) => prev.map((t, i) => (i === index ? { ...t, draftStatus: "Discarded" } : t))));

  return (
    <>
      <Fab color="primary" aria-label="Open HR Copilot" onClick={() => setOpen(true)} sx={{ position: "fixed", bottom: 24, right: 24, zIndex: (t) => t.zIndex.drawer + 1 }}>
        <ChatOutlinedIcon />
      </Fab>
      <Drawer anchor="right" open={open} onClose={() => setOpen(false)} PaperProps={{ sx: { width: { xs: "100%", sm: 420 }, p: 2 } }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" mb={1}>
          <Typography variant="h6">HR Copilot</Typography>
          <IconButton aria-label="Close HR Copilot" onClick={() => setOpen(false)}>
            <CloseIcon />
          </IconButton>
        </Stack>
        <Box sx={{ flex: 1, overflowY: "auto" }} aria-live="polite">
          {turns.length === 0 && (
            <Typography color="text.secondary" variant="body2">
              Ask about your organisation's policies, your assets, tickets or pending approvals. Answers cite the policy they come from.
            </Typography>
          )}
          {turns.map((turn, i) => (
            <Box key={i} sx={{ mb: 2 }}>
              <Typography variant="subtitle2">{turn.question}</Typography>
              {turn.error && <Alert severity="warning" sx={{ mt: 1 }}>{turn.error}</Alert>}
              {turn.reply && (
                <Box sx={{ mt: 1 }}>
                  <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>{turn.reply.answer}</Typography>
                  {turn.reply.citations.length > 0 && (
                    <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
                      {turn.reply.citations.map((c) => (
                        <Chip key={c.n} size="small" variant="outlined" label={`[${c.n}] ${c.title}${c.heading ? ` · ${c.heading}` : ""}`} title={c.excerpt} />
                      ))}
                    </Stack>
                  )}
                  {turn.reply.draft && !turn.draftStatus && (
                    <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                      <Button size="small" variant="contained" onClick={() => confirm(i, turn.reply!.draft!.id)}>Confirm & submit</Button>
                      <Button size="small" onClick={() => discard(i, turn.reply!.draft!.id)}>Discard</Button>
                    </Stack>
                  )}
                  {turn.draftStatus && <Typography variant="caption" color="text.secondary">{turn.draftStatus}</Typography>}
                </Box>
              )}
            </Box>
          ))}
        </Box>
        <Stack direction="row" spacing={1} alignItems="flex-start" sx={{ mt: 1 }}>
          <TextField select size="small" value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="Answer language" sx={{ width: 110 }}>
            {LANGUAGES.map((l) => (
              <MenuItem key={l.code} value={l.code}>{l.label}</MenuItem>
            ))}
          </TextField>
          <TextField
            size="small"
            fullWidth
            multiline
            maxRows={4}
            placeholder="Ask a question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                ask();
              }
            }}
            inputProps={{ "aria-label": "Question for HR Copilot" }}
          />
          <Button variant="contained" onClick={ask} disabled={busy || !question.trim()}>Ask</Button>
        </Stack>
      </Drawer>
    </>
  );
}
