import { useState } from "react";
import MenuItem from "@mui/material/MenuItem";

import { extractErrorMessage, hasErrorCode, interviewSchedulingApi } from "../api/client";
import { shortlistStatusOf, type CandidateApplicationRow } from "../api/types";

// Shared by every List page that can show a Shortlisted ('hr_selected') row -- Shortlisting
// List and Screening List alike, since Screening List's own applications query has no
// default status restriction (see ScreeningListPage.tsx listParams) and can show the exact
// same stuck rows Shortlisting List does. One implementation so eligibility/handler/copy
// can never drift between pages the way check_retry_eligibility and the backend's own
// idempotency guard once did (see backend app/interview_scheduling/negotiation.py).
//
// Coarse, list-level gate -- "Shortlisted" is a necessary condition for eligibility, not a
// sufficient one (see backend check_retry_eligibility for the full rule: no Interview yet,
// no batch still mid-flight). Deliberately shown any time the application is Shortlisted,
// not only once a send has actually failed, since there's no cheap per-row signal for "the
// last attempt failed" on a list without an extra join per row -- clicking it while
// genuinely ineligible just surfaces the backend's own reason as an error, same as every
// other action here.
export function isRetryNegotiationEligible(row: CandidateApplicationRow): boolean {
  return shortlistStatusOf(row.status) === "shortlisted";
}

export default function RetryNegotiationMenuItem({
  row,
  onClose,
  onDone,
  onError,
}: {
  row: CandidateApplicationRow;
  onClose: () => void;
  onDone: () => void;
  onError: (message: string) => void;
}) {
  const [retrying, setRetrying] = useState(false);

  const handleClick = async () => {
    onClose();
    setRetrying(true);
    try {
      const result = await interviewSchedulingApi.retryNegotiation(row.application_id);
      if (result.outcome !== "started") {
        onError(
          result.reason
            ? `Retry for ${row.candidate_name || "this candidate"} did not start a new negotiation: ${result.reason}`
            : `Retry for ${row.candidate_name || "this candidate"} did not start a new negotiation -- check Remarks/the Interview Log tracker for why (e.g. the HR mailbox still isn't reachable).`,
        );
      }
      onDone();
    } catch (err) {
      if (hasErrorCode(err, "TRACKER_LOCKED")) {
        onError("Tracker file is open in Excel -- close it and retry.");
      } else {
        onError(extractErrorMessage(err, "Failed to retry interview scheduling"));
      }
    } finally {
      setRetrying(false);
    }
  };

  return (
    <MenuItem disabled={retrying} onClick={handleClick}>
      Retry Scheduling
    </MenuItem>
  );
}
