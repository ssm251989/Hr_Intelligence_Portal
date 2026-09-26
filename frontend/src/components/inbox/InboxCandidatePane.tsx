import { useEffect, useState } from "react";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { applicationsApi, candidatesApi } from "../../api/client";
import { inboxExtraApi } from "../../api/interviewsExtra";
import type { CandidateApplicationDetail, CandidateApplicationRow, HrInboundEmailRead } from "../../api/types";
import { useT } from "../../i18n";
import Emoji from "../../ui-kit/Emoji";
import FriendlyError from "../../ui-kit/FriendlyError";
import InfoTip from "../../ui-kit/InfoTip";
import StatusChip from "../../ui-kit/StatusChip";
import UserAvatar from "../../ui-kit/UserAvatar";

// Right pane (spec H1/H2/H3): who this mail is from. Auto-linked mail shows the candidate;
// unmatched mail shows the "Assign to candidate" step (backend ui_interviews_router
// assign_inbox_email), which can also link the sender's other unmatched mail.
export default function InboxCandidatePane({ email, onAssigned }: { email: HrInboundEmailRead; onAssigned: () => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;

  if (email.matched_application_id) return <LinkedCandidate applicationId={email.matched_application_id} fallbackName={email.matched_candidate_name} jobTitle={email.matched_job_title} />;
  if (email.matched_candidate_id) {
    return (
      <Stack spacing={1.5}>
        <PaneTitle />
        <Stack direction="row" spacing={1.25} alignItems="center">
          <UserAvatar name={email.matched_candidate_name || email.from_address} size={44} />
          <Typography sx={{ fontWeight: 700 }}>{email.matched_candidate_name || t("inbox.candidate.matched")}</Typography>
        </Stack>
        <StatusChip tone="ok" emoji="link" label={t("inbox.linked")} />
      </Stack>
    );
  }
  return (
    <Stack spacing={1.5}>
      <PaneTitle />
      <Stack direction="row" spacing={1} alignItems="center" sx={{ p: 1.5, borderRadius: "12px", bgcolor: f.sunSoft }}>
        <Emoji name="question" size={20} />
        <Typography sx={{ fontSize: 14, color: f.sunInk, fontWeight: 600 }}>{t("inbox.candidate.unmatched")}</Typography>
      </Stack>
      <AssignToCandidate email={email} onAssigned={onAssigned} />
    </Stack>
  );
}

function PaneTitle() {
  const t = useT();
  return (
    <Stack direction="row" spacing={1} alignItems="center">
      <Emoji name="technologist" size={20} />
      <Typography component="h2" sx={{ fontWeight: 800, fontSize: 16 }}>{t("inbox.candidate.title")}</Typography>
    </Stack>
  );
}

function LinkedCandidate({ applicationId, fallbackName, jobTitle }: { applicationId: string; fallbackName?: string | null; jobTitle?: string | null }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [detail, setDetail] = useState<CandidateApplicationDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    applicationsApi
      .candidateDetail(applicationId)
      .then((d) => alive && setDetail(d))
      .catch(() => alive && setDetail(null))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [applicationId]);

  const c = detail?.candidate;
  const name = c?.full_name || fallbackName || t("interviews.unnamed");
  const skills = c?.parsed_fields?.skills?.slice(0, 8) ?? [];
  const facts: [string, string | null | undefined][] = [
    [t("inbox.candidate.job"), detail?.job_title || jobTitle],
    [t("inbox.candidate.email"), c?.email],
    [t("inbox.candidate.phone"), c?.phone],
    [t("inbox.candidate.location"), c?.location],
    [t("inbox.candidate.experience"), c?.parsed_fields?.total_experience_years != null ? t("interviews.my.experience", { count: c.parsed_fields.total_experience_years }) : null],
  ];

  return (
    <Stack spacing={1.5}>
      <PaneTitle />
      {loading ? (
        <Skeleton variant="rounded" height={160} />
      ) : (
        <>
          <Stack direction="row" spacing={1.25} alignItems="center">
            <UserAvatar name={name} size={48} />
            <Box sx={{ minWidth: 0 }}>
              <Typography sx={{ fontWeight: 800 }}>{name}</Typography>
              <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 0.5 }}>
                <StatusChip tone="ok" emoji="link" label={t("inbox.linked")} />
                {detail?.application.status && <StatusChip status={detail.application.status} />}
              </Stack>
            </Box>
          </Stack>
          <Box component="dl" sx={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 12px", m: 0, fontSize: 13 }}>
            {facts.filter(([, v]) => v).map(([k, v]) => (
              <Box key={k} sx={{ display: "contents" }}>
                <Typography component="dt" sx={{ color: f.muted, fontSize: 13 }}>{k}</Typography>
                <Typography component="dd" sx={{ m: 0, fontWeight: 600, fontSize: 13, wordBreak: "break-word" }}>{v}</Typography>
              </Box>
            ))}
          </Box>
          {skills.length > 0 && (
            <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
              {skills.map((s) => (
                <StatusChip key={s} tone="brand" emoji="check" label={s} />
              ))}
            </Stack>
          )}
          <Button variant="outlined" component={RouterLink} to={`/candidates/${applicationId}`}>
            {t("inbox.candidate.open")}
          </Button>
        </>
      )}
    </Stack>
  );
}

function AssignToCandidate({ email, onAssigned }: { email: HrInboundEmailRead; onAssigned: () => void }) {
  const t = useT();
  const [input, setInput] = useState("");
  const [options, setOptions] = useState<CandidateApplicationRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [choice, setChoice] = useState<CandidateApplicationRow | null>(null);
  const [sameSender, setSameSender] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setChoice(null);
    setError(null);
    // Start with the sender's address -- often the candidate simply used another inbox.
    setInput(email.from_address.split("@")[0] ?? "");
  }, [email.id, email.from_address]);

  useEffect(() => {
    const q = input.trim();
    if (q.length < 2) {
      setOptions([]);
      return;
    }
    const handle = setTimeout(() => {
      setLoading(true);
      candidatesApi
        .listApplications({ search: q, pageSize: 20 })
        .then((r) => setOptions(r.items))
        .catch(() => setOptions([]))
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(handle);
  }, [input]);

  const assign = () => {
    if (!choice) return;
    setSaving(true);
    setError(null);
    inboxExtraApi
      .assign(email.id, choice.application_id, sameSender)
      .then(onAssigned)
      .catch(setError)
      .finally(() => setSaving(false));
  };

  return (
    <Box component="section" aria-label={t("inbox.assign.title")}>
      <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 1 }}>
        <Typography sx={{ fontWeight: 700 }}>{t("inbox.assign.title")}</Typography>
        <InfoTip text={t("inbox.assign.info")} />
      </Stack>
      <Stack spacing={1.25}>
        <Autocomplete
          options={options}
          loading={loading}
          value={choice}
          onChange={(_e, v) => setChoice(v)}
          inputValue={input}
          onInputChange={(_e, v, reason) => reason !== "reset" && setInput(v)}
          filterOptions={(x) => x}
          getOptionLabel={(o) => `${o.candidate_name || t("interviews.unnamed")} — ${o.job_title}`}
          isOptionEqualToValue={(a, b) => a.application_id === b.application_id}
          noOptionsText={input.trim().length < 2 ? t("inbox.assign.type_more") : t("inbox.assign.no_match")}
          renderOption={(props, o) => (
            <li {...props} key={o.application_id}>
              <Stack direction="row" spacing={1} alignItems="center">
                <UserAvatar name={o.candidate_name || "?"} size={28} />
                <Box>
                  <Typography sx={{ fontSize: 14, fontWeight: 600 }}>{o.candidate_name || t("interviews.unnamed")}</Typography>
                  <Typography sx={{ fontSize: 12, opacity: 0.7 }}>{[o.job_title, o.candidate_email].filter(Boolean).join(" · ")}</Typography>
                </Box>
              </Stack>
            </li>
          )}
          renderInput={(params) => <TextField {...params} size="small" label={t("inbox.assign.search")} />}
        />
        <FormControlLabel control={<Checkbox checked={sameSender} onChange={(e) => setSameSender(e.target.checked)} />} label={t("inbox.assign.same_sender")} />
        {error ? <FriendlyError error={error} compact /> : null}
        <Button variant="contained" onClick={assign} disabled={!choice || saving}>
          {saving ? t("inbox.assign.saving") : t("inbox.assign.button")}
        </Button>
      </Stack>
    </Box>
  );
}
