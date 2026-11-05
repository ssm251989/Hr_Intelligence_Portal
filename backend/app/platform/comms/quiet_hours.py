"""Quiet hours + digest gating (docs/HRMS_COMPLETE_SPEC.txt Part 4 section 1's
notification_rules.quiet_hours_respect/digest_mode). Scoped down: this module answers
"should THIS send happen right now, or hold for later" -- it does not itself implement the
"later" half (a scheduled resume once quiet hours end, or a periodic digest-compilation
job) since both need live Celery beat scheduling this installation doesn't have a worker
running for yet (same deferral as Part 2's own TenantTask). A held send is left in
outbound_messages with status="queued" -- correctly NOT sent, and visible in the message
log -- rather than silently dropped; actually flushing it is the deferred half.
"""

from datetime import datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo


def is_within_quiet_hours(quiet_hours_json: Optional[dict], now: Optional[datetime] = None) -> bool:
    """quiet_hours_json shape: {"start": "22:00", "end": "07:00", "tz": "Asia/Kolkata"} --
    handles an overnight window (start > end) by wrapping past midnight."""
    if not quiet_hours_json:
        return False
    now = now or datetime.now(timezone.utc)
    tz = ZoneInfo(quiet_hours_json.get("tz", "Asia/Kolkata"))
    local_now = now.astimezone(tz).time()
    start = time.fromisoformat(quiet_hours_json["start"])
    end = time.fromisoformat(quiet_hours_json["end"])
    if start <= end:
        return start <= local_now < end
    return local_now >= start or local_now < end  # overnight window, e.g. 22:00 -> 07:00


def should_hold_for_quiet_hours(rule_quiet_hours_respect: bool, recipient_quiet_hours_json: Optional[dict], now: Optional[datetime] = None) -> bool:
    if not rule_quiet_hours_respect:
        return False
    return is_within_quiet_hours(recipient_quiet_hours_json, now)


def should_hold_for_digest(digest_mode: str) -> bool:
    """True for "hourly"/"daily" -- section 1's own digest_mode values; a digest send is
    always held for the (not-yet-built) compilation job rather than going out immediately,
    since the whole point of digest_mode is "batch these, don't send one-by-one"."""
    return digest_mode in ("hourly", "daily")
