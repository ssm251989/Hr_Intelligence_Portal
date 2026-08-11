from typing import Optional

import gender_guesser.detector as gender_detector

# A dataset-based lookup, not an LLM call -- this is purely for picking which generic
# fallback avatar illustration to show when a candidate has no real extracted photo, so a
# cheap, deterministic, offline library is the right tool, not an API round-trip.
_detector = gender_detector.Detector(case_sensitive=False)

# "male"/"mostly_male" and "female"/"mostly_female" both count as confident enough to show
# a gendered illustration; "andy" (androgynous -- used about equally by both) and "unknown"
# (no data for this name) are deliberately excluded, so an ambiguous name falls back to
# initials instead of forcing a coin-flip guess.
_CONFIDENT_RESULTS = {
    "male": "male",
    "mostly_male": "male",
    "female": "female",
    "mostly_female": "female",
}


def infer_gender(full_name: Optional[str]) -> Optional[str]:
    """Best-effort, name-based gender guess for a purely cosmetic fallback avatar -- never
    used for anything about the candidate besides which generic illustration to show.
    Returns "male"/"female" only when the first name's lookup is reasonably confident;
    None otherwise (no name, no data for this name, or a genuinely androgynous one).
    """
    if not full_name:
        return None
    parts = full_name.split()
    if not parts:
        return None
    return _CONFIDENT_RESULTS.get(_detector.get_gender(parts[0]))
