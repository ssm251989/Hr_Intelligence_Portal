// feat 2026-10-06: the actionable exit checklist. Every item opens to show its owner, due date, history and the
// buttons that really finish it (backend/app/employees/exit_checklist.py decides which buttons each person gets).
// Used on HR's exit dialog, on the leaving employee's own exit page and in "My exit tasks" for owners.
import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Collapse from "@mui/material/Collapse";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { employeesApi } from "../../api/employeesApi";
import { exitChecklistApi, type Checklist, type ChecklistItem, type ItemAction, type ItemStatus } from "../../api/exitChecklistApi";
import { useT } from "../../i18n";
import { Emoji, StatusChip, type Tone } from "../../ui-kit";
import { useDateFmt } from "../servicedesk/shared";

const STATUS: Record<ItemStatus, { tone: Tone; emoji: string }> = {
  todo: { tone: "sun", emoji: "hourglass" }, requested: { tone: "sky", emoji: "envelope" }, waiting_confirmation: { tone: "brand", emoji: "eyes" },
  done: { tone: "ok", emoji: "check" }, not_applicable: { tone: "muted", emoji: "pause" }, blocked: { tone: "coral", emoji: "lock" },
};
const CLOSED: ItemStatus[] = ["done", "not_applicable"];

export function ChecklistStatusChip({ status, overdue }: { status: string; overdue?: boolean }) {
  const t = useT();
  if (overdue) return <StatusChip tone="coral" emoji="alarm_clock" label={t("xc.status.overdue")} />;
  const s = STATUS[status as ItemStatus] ?? STATUS.todo;
  return <StatusChip tone={s.tone} emoji={s.emoji} label={t(`xc.status.${status in STATUS ? status : "todo"}`)} />;
}

async function openBlob(p: Promise<Blob | null>) {
  const blob = await p;
  if (blob) window.open(URL.createObjectURL(blob), "_blank", "noopener");
}

type Run = (action: ItemAction, data?: Record<string, unknown>) => Promise<void>;

function ItemActions({ item, run, busy }: { item: ChecklistItem; run: Run; busy: boolean }) {
  const t = useT();
  const has = (a: ItemAction) => item.actions.includes(a);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [condition, setCondition] = useState("good");
  const [amount, setAmount] = useState("");
  const [recover, setRecover] = useState("");
  const [pay, setPay] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [takeover, setTakeover] = useState<{ id: string | null; name: string } | null>(null);
  const [people, setPeople] = useState<{ id: string | null; name: string }[]>([]);
  const [mode, setMode] = useState<null | "lost" | "reason_na" | "reason_block">(null);

  useEffect(() => {
    if (!has("sign_off")) return;
    employeesApi.list({ status: "active" }).then((r) => setPeople(r.items.map((e) => ({ id: e.id, name: `${e.name} (${e.employee_code})` })))).catch(() => setPeople([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  const withFile = async (action: ItemAction, data: Record<string, unknown>, key: string) => {
    let ref: string | undefined;
    if (file) ref = (await exitChecklistApi.upload(item.id, file)).file;
    await run(action, { ...data, ...(ref ? { [key]: ref } : {}) });
  };

  const row = { direction: { xs: "column", sm: "row" } as const, spacing: 1, alignItems: { sm: "center" }, flexWrap: "wrap" as const, useFlexGap: true };
  const fileInput = (label: string) => (
    <Button component="label" variant="text" size="small" startIcon={<Emoji name="link" size={14} />}>
      {file ? file.name : label}
      <input hidden type="file" accept="image/*,.pdf,.doc,.docx,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
    </Button>
  );

  return (
    <Stack spacing={1.25}>
      {has("request_return") && (
        <Box><Button variant="contained" size="small" disabled={busy} onClick={() => run("request_return")}>{t("xc.act.request_return")}</Button>
          <Typography component="span" sx={{ fontSize: 12, ml: 1, color: "text.secondary" }}>{t("xc.act.request_return_hint")}</Typography></Box>
      )}
      {has("employee_returned") && (
        <Stack {...row}>
          <TextField size="small" label={t("xc.f.return_note")} value={note} onChange={(e) => setNote(e.target.value)} sx={{ minWidth: 260 }} />
          {fileInput(t("xc.f.photo"))}
          <Button variant="contained" size="small" disabled={busy} onClick={() => withFile("employee_returned", { note }, "photo")}>{t("xc.act.employee_returned")}</Button>
        </Stack>
      )}
      {has("received") && mode !== "lost" && (
        <Stack {...row}>
          <TextField select size="small" label={t("xc.f.condition")} value={condition} onChange={(e) => setCondition(e.target.value)} sx={{ minWidth: 180 }}>
            {["good", "damaged", "missing_parts"].map((c) => <MenuItem key={c} value={c}>{t(`xc.cond.${c}`)}</MenuItem>)}
          </TextField>
          <TextField size="small" label={t("xc.f.note")} value={note} onChange={(e) => setNote(e.target.value)} />
          <Button variant="contained" size="small" color="success" disabled={busy} onClick={() => run("received", { condition, note })}>{t("xc.act.received")}</Button>
          {has("lost") && <Button size="small" color="error" onClick={() => setMode("lost")}>{t("xc.act.lost")}</Button>}
        </Stack>
      )}
      {mode === "lost" && (
        <Stack {...row}>
          <TextField size="small" type="number" label={t("xc.f.recover_amount")} value={amount} onChange={(e) => setAmount(e.target.value)} inputProps={{ min: 0 }} />
          <TextField size="small" label={t("xc.f.note")} value={note} onChange={(e) => setNote(e.target.value)} />
          <Button variant="contained" size="small" color="error" disabled={busy} onClick={() => run("lost", { amount: Number(amount) || 0, note })}>{t("xc.act.lost_confirm")}</Button>
          <Button size="small" onClick={() => setMode(null)}>{t("action.cancel")}</Button>
        </Stack>
      )}
      {(has("revoke_now") || has("revoke_last_day")) && (
        <Stack {...row}>
          {has("revoke_now") && <Button variant="contained" size="small" color="error" disabled={busy} onClick={() => run("revoke_now")}>{t("xc.act.revoke_now")}</Button>}
          {has("revoke_last_day") && <Button variant="outlined" size="small" disabled={busy} onClick={() => run("revoke_last_day")}>{t("xc.act.revoke_last_day")}</Button>}
          <Typography sx={{ fontSize: 12, color: "text.secondary" }}>{t("xc.act.revoke_hint")}</Typography>
        </Stack>
      )}
      {has("confirm_manual") && (
        <Stack {...row}>
          <TextField size="small" label={t("xc.f.note")} value={note} onChange={(e) => setNote(e.target.value)} />
          <Button variant="contained" size="small" disabled={busy} onClick={() => run("confirm_manual", { note })}>{t("xc.act.confirm_manual")}</Button>
        </Stack>
      )}
      {has("settle") && (
        <Stack {...row}>
          <TextField size="small" type="number" label={t("xc.f.recover")} value={recover} onChange={(e) => setRecover(e.target.value)} inputProps={{ min: 0 }} sx={{ width: 150 }} />
          <TextField size="small" type="number" label={t("xc.f.pay")} value={pay} onChange={(e) => setPay(e.target.value)} inputProps={{ min: 0 }} sx={{ width: 150 }} />
          <TextField size="small" label={t("xc.f.note")} value={note} onChange={(e) => setNote(e.target.value)} />
          <Button variant="contained" size="small" disabled={busy || (!recover && !pay)} onClick={() => run("settle", { recover: Number(recover) || 0, pay: Number(pay) || 0, note })}>{t("xc.act.settle")}</Button>
          <Button variant="outlined" size="small" disabled={busy} onClick={() => run("settle", { nothing_pending: true, note })}>{t("xc.act.nothing_pending")}</Button>
        </Stack>
      )}
      {has("sign_off") && (
        <Stack spacing={1}>
          <TextField multiline minRows={3} label={t("xc.f.handover_notes")} placeholder={t("xc.f.handover_ph")} value={note} onChange={(e) => setNote(e.target.value)} fullWidth />
          <Stack {...row}>
            <Autocomplete freeSolo size="small" sx={{ minWidth: 280 }} options={people} getOptionLabel={(o) => (typeof o === "string" ? o : o.name)}
              value={takeover} onChange={(_, v) => setTakeover(typeof v === "string" ? { id: null, name: v } : v)}
              onInputChange={(_, v, why) => { if (why === "input") setTakeover(v ? { id: null, name: v } : null); }}
              renderInput={(p) => <TextField {...p} label={t("xc.f.takeover")} />} />
            {fileInput(t("xc.f.kt_doc"))}
            <Button variant="contained" size="small" disabled={busy || !note.trim()}
              onClick={() => withFile("sign_off", { notes: note, takeover_employee_id: takeover?.id ?? null, takeover_name: takeover?.id ? null : takeover?.name ?? null }, "document")}>
              {t("xc.act.sign_off")}</Button>
          </Stack>
        </Stack>
      )}
      {(has("generate_letters") || has("interview_na")) && (
        <Stack {...row}>
          {has("generate_letters") && <Button variant="contained" size="small" disabled={busy} onClick={() => run("generate_letters")}>{t("xc.act.generate_letters")}</Button>}
          {has("interview_na") && !item.details.interview_na && (
            <>
              <TextField size="small" label={t("xc.f.interview_na_reason")} value={reason} onChange={(e) => setReason(e.target.value)} sx={{ minWidth: 240 }} />
              <Button size="small" variant="outlined" disabled={busy || !reason.trim()} onClick={() => run("interview_na", { reason })}>{t("xc.act.interview_na")}</Button>
            </>
          )}
        </Stack>
      )}
      {has("mark_done") && (
        <Stack {...row}>
          <TextField size="small" label={t("xc.f.note")} value={note} onChange={(e) => setNote(e.target.value)} />
          <Button variant="contained" size="small" disabled={busy} onClick={() => run("mark_done", { note })}>{t("xc.act.mark_done")}</Button>
        </Stack>
      )}
      {(mode === "reason_na" || mode === "reason_block") ? (
        <Stack {...row}>
          <TextField size="small" autoFocus label={t("xc.f.reason")} value={reason} onChange={(e) => setReason(e.target.value)} sx={{ minWidth: 260 }} />
          <Button size="small" variant="contained" disabled={busy || !reason.trim()} onClick={() => run(mode === "reason_na" ? "not_applicable" : "block", { reason }).then(() => setMode(null))}>
            {t(mode === "reason_na" ? "xc.act.not_applicable" : "xc.act.block")}</Button>
          <Button size="small" onClick={() => setMode(null)}>{t("action.cancel")}</Button>
        </Stack>
      ) : (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {has("unblock") && <Button size="small" disabled={busy} onClick={() => run("unblock")}>{t("xc.act.unblock")}</Button>}
          {has("block") && <Button size="small" color="warning" onClick={() => setMode("reason_block")}>{t("xc.act.block")}</Button>}
          {has("not_applicable") && <Button size="small" color="inherit" onClick={() => setMode("reason_na")}>{t("xc.act.not_applicable")}</Button>}
          {has("reopen") && <Button size="small" disabled={busy} onClick={() => run("reopen")}>{t("xc.act.reopen")}</Button>}
        </Stack>
      )}
    </Stack>
  );
}

function Details({ item }: { item: ChecklistItem }) {
  const t = useT();
  const fmt = useDateFmt();
  const d = item.details;
  const lines: string[] = [];
  if (d.employee_returned) lines.push(t("xc.d.employee_returned", { date: fmt.dateTime(d.employee_returned.at) }) + (d.employee_returned.note ? ` - "${d.employee_returned.note}"` : ""));
  if (d.received) lines.push(t("xc.d.received", { cond: t(`xc.cond.${d.received.condition}`), by: d.received.by }));
  if (d.lost) lines.push(t("xc.d.lost", { amount: d.lost.amount }));
  if (d.scheduled_for) lines.push(t("xc.d.scheduled", { date: fmt.date(d.scheduled_for) }));
  if (d.app_login) lines.push(t(`xc.d.app_login.${d.app_login === "disabled" ? "off" : "none"}`));
  if (d.mailbox) lines.push(d.mailbox.mode === "provider" ? t("xc.d.mailbox_suspended", { provider: d.mailbox.provider }) : d.mailbox.mode === "it_todo" ? t("xc.d.mailbox_it") : t("xc.d.mailbox_none"));
  for (const r of d.recoveries ?? []) lines.push(t("xc.d.recovery", { item: r.item, amount: r.amount }));
  if (d.settlement) lines.push(d.settlement.nothing_pending ? t("xc.d.nothing_pending") : t("xc.d.settled", { recover: d.settlement.recover, pay: d.settlement.pay }));
  if (d.handover) lines.push(t("xc.d.handover", { by: d.handover.by }) + (d.handover.takeover ? ` - ${t("xc.d.takeover", { name: d.handover.takeover.name })}` : ""));
  if (d.interview_na) lines.push(t("xc.d.interview_na", { reason: d.interview_na.reason }));
  const files: [string, string][] = [];
  if (d.employee_returned?.photo) files.push([t("xc.f.photo"), d.employee_returned.photo]);
  if (d.handover?.document) files.push([t("xc.f.kt_doc"), d.handover.document]);
  if (!lines.length && !files.length && !d.handover?.notes) return null;
  return (
    <Stack spacing={0.5}>
      {lines.map((l) => <Typography key={l} sx={{ fontSize: 13 }}>• {l}</Typography>)}
      {d.handover?.notes && <Typography sx={{ fontSize: 13, whiteSpace: "pre-wrap", bgcolor: "action.hover", borderRadius: 1, p: 1 }}>{d.handover.notes}</Typography>}
      {files.map(([label, ref]) => (
        <Box key={ref}><Button size="small" startIcon={<Emoji name="link" size={14} />} onClick={() => openBlob(exitChecklistApi.fileBlob(ref))}>{label}</Button></Box>
      ))}
    </Stack>
  );
}

function ItemRow({ item, open, onToggle, onChanged }: { item: ChecklistItem; open: boolean; onToggle: () => void; onChanged: (c: Checklist) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run: Run = async (action, data = {}) => {
    setBusy(true);
    setError(null);
    try {
      onChanged(await exitChecklistApi.act(item.id, action, data));
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    } finally {
      setBusy(false);
    }
  };
  const closed = CLOSED.includes(item.status);
  const owner = item.owner_name || (item.owner_role ? t(`xc.role.${item.owner_role}`) : "—");
  return (
    <Box component="li" data-testid={`xc-item-${item.id}`} sx={{ border: `1px solid ${item.overdue ? f.coral : open ? f.brand : f.line}`, borderRadius: "12px", bgcolor: closed ? f.surface2 : f.surface }}>
      <Box component="button" type="button" onClick={onToggle} aria-expanded={open}
        sx={{ all: "unset", boxSizing: "border-box", width: "100%", cursor: "pointer", display: "flex", gap: 1, alignItems: "center", flexWrap: "wrap", px: 1.5, py: 1.1,
          "&:focus-visible": { outline: `2px solid ${f.brand}`, borderRadius: "12px" } }}>
        <Emoji name={closed ? "check" : item.kind === "asset_recovery" || item.kind === "id_card" ? "laptop" : "clipboard"} size={16} />
        <Typography sx={{ flex: 1, minWidth: 180, fontSize: 14, fontWeight: closed ? 500 : 700, textDecoration: item.status === "not_applicable" ? "line-through" : "none" }}>{item.title}</Typography>
        <Typography sx={{ fontSize: 12, color: f.muted }}>{owner}</Typography>
        {item.due_date && !closed && <Typography sx={{ fontSize: 12, color: item.overdue ? "error.main" : f.muted }}>{t("xc.due", { date: fmt.date(item.due_date) })}</Typography>}
        {!item.required && <StatusChip tone="muted" emoji="label" label={t("xc.optional")} />}
        <ChecklistStatusChip status={item.status} overdue={item.overdue} />
        {item.actions.length > 0 && !closed && <StatusChip tone="brand" emoji="bell" label={t("xc.your_turn")} />}
      </Box>
      <Collapse in={open} unmountOnExit>
        <Stack spacing={1.25} sx={{ px: 1.5, pb: 1.5 }}>
          {item.reason && <Alert severity={item.status === "blocked" ? "warning" : "info"} sx={{ py: 0 }}>{item.reason}</Alert>}
          <Details item={item} />
          {error && <Alert severity="error">{error}</Alert>}
          {item.actions.length > 0 ? <ItemActions item={item} run={run} busy={busy} />
            : !closed && <Typography sx={{ fontSize: 13, color: f.muted }}>{t("xc.waiting_on", { owner })}</Typography>}
          {item.history.length > 0 && (
            <Box>
              <Typography sx={{ fontSize: 12, fontWeight: 700, color: f.muted, mb: 0.25 }}>{t("xc.history")}</Typography>
              {[...item.history].reverse().map((h, i) => (
                <Typography key={`${h.at}-${i}`} sx={{ fontSize: 12, color: f.muted }}>
                  {fmt.dateTime(h.at)} · {h.actor} · {t(`xc.h.${h.action}`) === `xc.h.${h.action}` ? h.action.replace(/_/g, " ") : t(`xc.h.${h.action}`)}{h.note ? ` - ${h.note}` : ""}
                </Typography>
              ))}
            </Box>
          )}
        </Stack>
      </Collapse>
    </Box>
  );
}

/** One exit's checklist. `separationId` = HR / owner view; omit it for the leaving employee's own exit. */
export default function ExitChecklist({ separationId, focusItemId, onChanged, onToast }: {
  separationId?: string; focusItemId?: string | null; onChanged?: () => void; onToast?: (m: string) => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const [data, setData] = useState<Checklist | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(focusItemId ?? null);
  const [extendTo, setExtendTo] = useState("");
  const [closeReason, setCloseReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    (separationId ? exitChecklistApi.get(separationId) : exitChecklistApi.mine()).then(setData).catch((e) => setError(extractErrorMessage(e, "")));
  }, [separationId]);
  useEffect(load, [load]);
  useEffect(() => { if (focusItemId) setOpenId(focusItemId); }, [focusItemId]);

  const changed = (c: Checklist) => { setData(c); onChanged?.(); };
  const hr = async (fn: () => Promise<Checklist>, msg: string) => {
    setBusy(true);
    setError(null);
    try {
      changed(await fn());
      onToast?.(msg);
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    } finally {
      setBusy(false);
    }
  };

  if (error && !data) return <Alert severity="error">{error}</Alert>;
  if (!data) return <LinearProgress aria-label={t("xc.loading")} />;
  if (!data.items.length) return <Typography sx={{ color: f.muted }}>{t(data.status === "completed" ? "xc.none_completed" : "xc.none_yet")}</Typography>;
  const sid = data.separation_id!;
  return (
    <Stack spacing={1.5} data-testid="exit-checklist">
      <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
        <Box sx={{ flex: 1, minWidth: 200 }}>
          <Typography sx={{ fontSize: 13, fontWeight: 700 }}>{t("xc.progress", { done: data.done ?? 0, total: data.total ?? 0 })}</Typography>
          <LinearProgress variant="determinate" value={data.percent ?? 0} sx={{ height: 8, borderRadius: 4, mt: 0.5 }} aria-label={t("xc.progress", { done: data.done ?? 0, total: data.total ?? 0 })} />
        </Box>
        {data.last_working_day && <Typography sx={{ fontSize: 13, color: f.muted }}>{t("xc.lwd", { date: fmt.date(data.last_working_day) })}</Typography>}
      </Stack>
      {data.status === "completed" && <Alert severity="success" icon={<Emoji name="check" size={16} />}>{t("xc.completed")}{data.completion_note ? ` ${t("xc.completed_note", { note: data.completion_note })}` : ""}</Alert>}
      {data.status !== "completed" && data.pending === 0 && !data.past_last_day && <Alert severity="info">{t("xc.all_done_waiting")}</Alert>}
      {data.pending_after_last_day && data.status !== "completed" && <Alert severity="warning">{t("xc.pending_after_lwd", { n: data.pending ?? 0 })}</Alert>}
      {error && <Alert severity="error">{error}</Alert>}
      <Stack component="ul" spacing={0.75} sx={{ listStyle: "none", p: 0, m: 0 }}>
        {data.items.map((i) => <ItemRow key={i.id} item={i} open={openId === i.id} onToggle={() => setOpenId(openId === i.id ? null : i.id)} onChanged={changed} />)}
      </Stack>
      {(data.letters?.relieving || data.letters?.experience) && (
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          {data.letters.relieving && <Button size="small" variant="outlined" startIcon={<Emoji name="page" size={14} />} onClick={() => openBlob(exitChecklistApi.letterBlob(data.letters!.relieving!))}>{t("xc.letter.relieving")}</Button>}
          {data.letters.experience && <Button size="small" variant="outlined" startIcon={<Emoji name="page" size={14} />} onClick={() => openBlob(exitChecklistApi.letterBlob(data.letters!.experience!))}>{t("xc.letter.experience")}</Button>}
          {data.letters_emailed_at && <Typography sx={{ fontSize: 12, color: f.muted }}>{t("xc.letter.emailed", { date: fmt.dateTime(data.letters_emailed_at) })}</Typography>}
        </Stack>
      )}
      {data.can_manage && separationId && ["approved", "clearance"].includes(data.status ?? "") && (
        <Stack spacing={1} sx={{ borderTop: `1px dashed ${f.line}`, pt: 1.5 }}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
            <TextField size="small" type="date" label={t("xc.extend")} value={extendTo} onChange={(e) => setExtendTo(e.target.value)} InputLabelProps={{ shrink: true }} />
            <Button size="small" variant="outlined" disabled={busy || !extendTo} onClick={() => hr(() => exitChecklistApi.extend(sid, extendTo), t("xc.extended"))}>{t("xc.extend_btn")}</Button>
          </Stack>
          {data.past_last_day && (data.pending ?? 0) > 0 && (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
              <TextField size="small" label={t("xc.close_reason")} value={closeReason} onChange={(e) => setCloseReason(e.target.value)} sx={{ minWidth: 300 }} />
              <Button size="small" color="error" variant="outlined" disabled={busy || !closeReason.trim()} onClick={() => hr(() => exitChecklistApi.complete(sid, closeReason), t("xc.closed"))}>{t("xc.close_btn")}</Button>
            </Stack>
          )}
        </Stack>
      )}
    </Stack>
  );
}

/** "My exit tasks": open items the signed-in person owns, across exits (IT, Admin, Finance, the manager). */
export function MyExitTasks({ focusItemId, onToast }: { focusItemId?: string | null; onToast?: (m: string) => void }) {
  const t = useT();
  const fmt = useDateFmt();
  const [items, setItems] = useState<ChecklistItem[] | null>(null);
  const [openSep, setOpenSep] = useState<string | null>(null);
  const load = useCallback(() => { exitChecklistApi.myTasks().then((r) => setItems(r.items)).catch(() => setItems([])); }, []);
  useEffect(load, [load]);
  useEffect(() => {
    const hit = items?.find((i) => i.id === focusItemId);
    if (hit?.separation_id) setOpenSep(hit.separation_id);
  }, [items, focusItemId]);
  if (!items?.length) return null;
  const bySep = items.reduce<Record<string, ChecklistItem[]>>((m, i) => ({ ...m, [i.separation_id!]: [...(m[i.separation_id!] ?? []), i] }), {});
  return (
    <Stack spacing={1} data-testid="my-exit-tasks">
      {Object.entries(bySep).map(([sid, list]) => (
        <Box key={sid}>
          <Button onClick={() => setOpenSep(openSep === sid ? null : sid)} sx={{ fontWeight: 800 }}>
            {t("xc.tasks_for", { name: list[0].employee_name ?? "", n: list.length })}{list.some((i) => i.overdue) ? ` · ${t("xc.status.overdue")}` : list[0].due_date ? ` · ${t("xc.due", { date: fmt.date(list[0].due_date) })}` : ""}
          </Button>
          <Collapse in={openSep === sid} unmountOnExit>
            <ExitChecklist separationId={sid} focusItemId={focusItemId} onChanged={load} onToast={onToast} />
          </Collapse>
        </Box>
      ))}
    </Stack>
  );
}
