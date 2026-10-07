import { useEffect, useMemo, useRef, useState } from "react";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import SearchIcon from "@mui/icons-material/Search";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Grid from "@mui/material/Grid";
import InputAdornment from "@mui/material/InputAdornment";
import Pagination from "@mui/material/Pagination";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { candidateEmailsApi, toInboundEmail, type CandidateEmailItem, type CandidateEmailPage, type CandidateEmailTab } from "../api/candidateEmailsApi";
import { hrInboxApi } from "../api/client";
import CandidateEmailCard from "../components/inbox/CandidateEmailCard";
import InboxCandidatePane from "../components/inbox/InboxCandidatePane";
import InboxThreadPane from "../components/inbox/InboxThreadPane";
import { useT } from "../i18n";
import Emoji from "../ui-kit/Emoji";
import EmptyState from "../ui-kit/EmptyState";
import FriendlyError from "../ui-kit/FriendlyError";
import PageHeader from "../ui-kit/PageHeader";
import { downloadCsv } from "../utils/csv";

const PAGE_SIZE = 25;
const SEARCH_DEBOUNCE_MS = 300;
const TABS: CandidateEmailTab[] = ["needs_action", "linked", "closed"];
// Settings -> Communication -> Mailboxes (settings/catalog.tsx).
const MAILBOX_SETTINGS_PATH = "/settings/communication/mailboxes";

// Part 17.7: "Candidate emails" (was "HR Inbox", also at /candidate-emails) -- replies from
// candidates to the company's emails. Three tabs (needs action / linked / not matched), one card
// per email with what it's about, and the thread + reply box (and "Assign to candidate" for
// unmatched mail) beside the list.
export default function HrInboxListPage() {
  const f = useTheme().palette.fresh;
  const t = useT();

  const [tab, setTab] = useState<CandidateEmailTab>("needs_action");
  const [data, setData] = useState<CandidateEmailPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [focusReply, setFocusReply] = useState(0);
  const assignRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchInput]);

  useEffect(() => {
    setPage(1);
  }, [search, tab]);

  const load = () => {
    setLoading(true);
    setError(null);
    candidateEmailsApi
      .list({ tab, search: search || undefined, page, pageSize: PAGE_SIZE })
      .then((r) => {
        setData(r);
        setSelectedId((cur) => (cur && r.items.some((i) => i.id === cur) ? cur : r.items[0]?.id ?? null));
      })
      .catch(setError)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, search, page, refreshKey]);

  const items = data?.items ?? [];
  const counts = data?.counts;
  const selectedItem = items.find((i) => i.id === selectedId) ?? null;
  // Memoised so the thread pane only reloads when the email itself changes.
  const selected = useMemo(
    () => (selectedItem ? toInboundEmail(selectedItem) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedItem?.id, selectedItem?.candidate_id, selectedItem?.application_id],
  );
  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));
  const refresh = () => setRefreshKey((k) => k + 1);

  const toggleDone = (email: CandidateEmailItem, done: boolean) => {
    setBusyId(email.id);
    setActionError(null);
    candidateEmailsApi
      .setDone(email.id, done)
      .then(refresh)
      .catch(setActionError)
      .finally(() => setBusyId(null));
  };

  const reply = (email: CandidateEmailItem) => {
    setSelectedId(email.id);
    setFocusReply((n) => n + 1);
  };

  const assign = (email: CandidateEmailItem) => {
    setSelectedId(email.id);
    setTimeout(() => assignRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  };

  const exportCsv = async () => {
    try {
      const rows = await hrInboxApi.export({ search: search || undefined });
      downloadCsv(
        "candidate-emails.csv",
        [t("inbox.col.from"), t("inbox.col.to"), t("inbox.col.subject"), t("inbox.col.received"), t("inbox.col.candidate"), t("inbox.col.job")],
        rows.map((r) => [r.from_address, r.to_address, r.subject, r.received_at, r.matched_candidate_name, r.matched_job_title]),
      );
    } catch (err) {
      setActionError(err);
    }
  };

  const connectButton = (
    <Button variant="contained" component={RouterLink} to={MAILBOX_SETTINGS_PATH} startIcon={<Emoji name="inbox" size={18} />}>
      {t("candidateEmails.connect")}
    </Button>
  );

  const emptyState = () => {
    if (search) {
      return (
        <EmptyState illustration="search" title={t("candidateEmails.empty.search")}
          action={<Button variant="outlined" onClick={() => setSearchInput("")}>{t("candidateEmails.empty.clear")}</Button>} />
      );
    }
    if (data && !data.mailbox_connected) {
      return <EmptyState illustration="empty-mailbox" title={t("candidateEmails.empty.no_mailbox")} hint={t("candidateEmails.how_it_works")} action={connectButton} />;
    }
    return <EmptyState illustration={tab === "needs_action" ? "done" : "empty-mailbox"} title={t(`candidateEmails.empty.${tab}`)} hint={t("candidateEmails.how_it_works")} />;
  };

  return (
    <Box>
      <PageHeader
        emoji="inbox"
        title={t("candidateEmails.title")}
        purpose={t("candidateEmails.purpose")}
        tourKey="hr-inbox"
        extra={
          <Button variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={exportCsv}>
            {t("candidateEmails.export")}
          </Button>
        }
      />

      {data && !data.mailbox_connected && (counts?.linked || counts?.closed || counts?.needs_action) ? (
        <Card sx={{ p: 1.5, mb: 2, bgcolor: f.sunSoft }}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "flex-start", sm: "center" }} justifyContent="space-between">
            <Stack direction="row" spacing={1} alignItems="center">
              <Emoji name="warning" size={20} />
              <Typography sx={{ fontSize: 14, color: f.sunInk, fontWeight: 600 }}>{t("candidateEmails.banner.no_mailbox")}</Typography>
            </Stack>
            {connectButton}
          </Stack>
        </Card>
      ) : null}

      <Card sx={{ px: 2, pt: 1, pb: 1.5, mb: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ xs: "stretch", md: "center" }} justifyContent="space-between">
          <Tabs value={tab} onChange={(_e, v: CandidateEmailTab) => setTab(v)} variant="scrollable" allowScrollButtonsMobile aria-label={t("candidateEmails.tabs.label")}>
            {TABS.map((k) => (
              <Tab key={k} value={k} sx={{ textTransform: "none", fontWeight: 700 }}
                label={counts ? t("candidateEmails.tabs.with_count", { label: t(`candidateEmails.tab.${k}`), count: counts[k] }) : t(`candidateEmails.tab.${k}`)} />
            ))}
          </Tabs>
          <TextField
            size="small"
            placeholder={t("candidateEmails.search")}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }, htmlInput: { "aria-label": t("candidateEmails.search") } }}
            sx={{ minWidth: 260 }}
          />
        </Stack>
        <Typography sx={{ color: f.muted, fontSize: 13, mt: 1 }}>{t(`candidateEmails.tab_hint.${tab}`)}</Typography>
      </Card>

      {actionError ? <Box sx={{ mb: 2 }}><FriendlyError error={actionError} compact /></Box> : null}

      {error ? (
        <FriendlyError error={error} onRetry={load} />
      ) : loading && !data ? (
        <Card sx={{ p: 2 }}>
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} variant="rounded" height={110} sx={{ mb: 1 }} />
          ))}
        </Card>
      ) : items.length === 0 ? (
        <Card>{emptyState()}</Card>
      ) : (
        <Grid container spacing={2} alignItems="flex-start">
          <Grid size={{ xs: 12, md: 5 }}>
            <Stack component="ul" aria-label={t("candidateEmails.list_label")} spacing={1} sx={{ listStyle: "none", m: 0, p: 0, opacity: loading ? 0.6 : 1 }}>
              {items.map((email) => (
                <Box component="li" key={email.id}>
                  <CandidateEmailCard
                    email={email}
                    selected={email.id === selectedId}
                    busy={busyId === email.id}
                    onSelect={() => setSelectedId(email.id)}
                    onReply={() => reply(email)}
                    onToggleDone={(done) => toggleDone(email, done)}
                    onAssign={() => assign(email)}
                    onLinked={refresh}
                  />
                </Box>
              ))}
            </Stack>
            {pageCount > 1 && (
              <Stack direction="row" justifyContent="center" mt={2}>
                <Pagination count={pageCount} page={page} onChange={(_e, v) => setPage(v)} size="small" color="primary" />
              </Stack>
            )}
          </Grid>
          <Grid size={{ xs: 12, md: 7 }}>
            <Stack spacing={2} sx={{ position: { md: "sticky" }, top: { md: 16 } }}>
              <Card sx={{ p: 2.25 }}>
                {selected ? (
                  <InboxThreadPane email={selected} focusReply={focusReply} onLinkedChanged={refresh} />
                ) : (
                  <EmptyState compact illustration="mailbox" title={t("inbox.pick")} />
                )}
              </Card>
              {selected && !selected.matched_application_id && (
                <Card sx={{ p: 2.25 }} ref={assignRef}>
                  <InboxCandidatePane email={selected} onAssigned={refresh} />
                </Card>
              )}
            </Stack>
          </Grid>
        </Grid>
      )}
    </Box>
  );
}
