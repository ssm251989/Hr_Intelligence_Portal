"""Part 23.3e: a short line that starts with a greeting was dropped whole, so "Hello, can I reschedule my call?"
signed "Vikas" got the summary "Vikas". Only the greeting is dropped now."""
import pytest

from app.hr_inbox.triage import first_sentence


@pytest.mark.parametrize("body, expected", [
    ("Hello, can I reschedule my call?\nVikas", "Can I reschedule my call?"),
    ("Good morning! Is the role still open?", "Is the role still open?"),
    ("Hi Priya,\nPlease find my degree certificate attached.\nMeena", "Please find my degree certificate attached."),
    ("Hi, can we move my interview to Thursday 11 am?\nThanks", "Hi, can we move my interview to Thursday 11 am?"),  # long line: unchanged
    ("Hello Priya, thanks", "Subject line"),  # nothing left after the greeting -> the subject
])
def test_summary_keeps_the_question_after_a_greeting(body, expected):
    assert first_sentence("Subject line", body) == expected
