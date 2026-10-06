# PART 21 - proof

Spec: docs/PART21_OWNER_CHANGES.txt. One section per item.

## 21.3 Bug: auto-shortlist "doesn't email the interviewer" (2026-10-06)

**Real cause, from the audit log of the two real cases (no code path was broken):**

`ce0f3340` (careers application, Junior AI Developer):
```
15:37:42 ai_auto_shortlisted system {'score': 96.0, ..., 'undo_until': '2026-10-07T05:07:42Z'}   <- 10:37 IST NEXT DAY
15:40:50 interview_negotiation_retry_triggered kg@ctdtechs.com                                    <- owner's "Retry", 3 min later
15:40:54 interview_negotiation_interviewer_attempt kg@ctdtechs.com {'outcome': 'offer_sent', 'interviewer': 'Kishore'}
```
`efa8bc20`: `22:40:21 ai_auto_shortlisted ... 'undo_until': '2026-10-06T07:30:00Z'` (13:00 IST next day), then Retry at 22:45.

- **The undo window is 4 working hours** (`recruitment.shortlisting.undo_hours` = 4, counted Mon-Fri inside business hours by `_add_business_hours`). An afternoon or evening shortlist therefore releases the next morning.
- **The release job was running fine:** Health `interview_automation` `{'ok': True, 'result': "{'ctd-techs': {'released': 0, 'retried': 0}}", every 60 s}`. `auto_shortlist_released` had **never** been written (count 0), because every test was retried by hand before its window ended.
- **The profile said** "Shortlisted - interview times go out soon", so it looked stuck.
- **Retry vs auto:** both ended in `attempt_auto_negotiate_interview_slots`, but **Retry skipped `automation.start()`**: the scheduling-mode check, the "never silent" problem to-do and the mailbox retries. A Retry inside the window also left the window open.

**Fix:**
- "Retry scheduling" (`negotiation.retry_negotiation`) now calls **the same `automation.start()`** as the auto release (trigger `retry`). A retry inside the undo window ends it (logged `auto_shortlist_released`, "retry scheduling (undo window ended early)"), so the background release can't start a second round.
- The profile now says **when** the emails go out: "Shortlisted - interview emails go out automatically at <date, time>" + "The undo window (working hours only) ends at …; then the interviewer and the candidate are emailed automatically. To start now, use Send interview times now." (en/hi/ta).
- Flow order unchanged (decision: it is the owner-approved interviewer-first negotiation). After the window, the **interviewer** is emailed first to pick times; the candidate then gets the choices; once the candidate picks, both get the invite + meeting link. Failures already show on the profile + Home to-do with the reason and a retry.

**Proof (no manual click by HR):**
- **Setup:**
  - a proof job with auto-shortlist and `undo_hours` 0
  - its own pool with demo interviewer Diya (TEST mailbox)
  - 2 proof candidates whose addresses were TEST mailboxes, so nothing left the server
  - the real auto-shortlist function `maybe_auto_shortlist` ran on both
- **What happened, by itself (the live app's minute job):**
```
20:35:58 ai_auto_shortlisted system   (both)
20:36:23/24 auto_shortlist_released system {'trigger': 'undo window closed'}
20:36:24 interview_negotiation_interviewer_attempt {'outcome': 'offer_sent', 'interviewer': 'Demo - Diya Nair'}
20:36:24 interview_scheduling_started {'trigger': 'auto_release'}
20:36:24 auto_shortlist_release_result {'outcome': 'started'}
```
- **Interviewer:** Diya's test inbox got both "Interview scheduling for Proof job - auto shortlist test" emails at 20:36:24 (fix21-as-01).
- **Candidates:** the interviewer then picked times on the email link (her action, not HR's). Both candidates' test inboxes got their time-choice email at 20:36:57. The profile shows "Waiting for Proof Auto One to pick a time - email sent 8:36 PM" (fix21-as-02).
- All proof records were removed afterwards.

Note: the proof used the TEST-mailbox inboxes instead of mailpit, because the release is done by the live app's background job (the point of the test), which doesn't use the proof stack's mail capture.
