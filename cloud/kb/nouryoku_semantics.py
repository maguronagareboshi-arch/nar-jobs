"""Pure, shared classifiers for structured nouryoku run metadata."""

from __future__ import annotations

import re
from typing import Any


# These labels are non-race examinations and must not be mixed with official
# finish/speed history.  Keep this classifier shared by live parsing and the
# one-time legacy-cache migration.
TRIAL_EVENT_RE = re.compile(r"(?:試験|能力検査|能力検定|発走検査)")
EVENT_LABEL_RE = re.compile(
    r"(?:^|\s)\d{1,2}\.\d{1,2}\s+(.+?)\s+\d+頭(?:\s|$)"
)


def is_trial_event_text(value: Any) -> bool:
    text = str(value or "").strip()
    match = EVENT_LABEL_RE.search(text)
    # On a full prior-run row only the event-name segment is eligible for
    # classification; jockey/opponent/horse names later in the row must not
    # create a false positive.  Accept a bare label for focused parser tests.
    label = match.group(1).strip() if match else text
    return bool(TRIAL_EVENT_RE.search(label))


__all__ = ["EVENT_LABEL_RE", "TRIAL_EVENT_RE", "is_trial_event_text"]
