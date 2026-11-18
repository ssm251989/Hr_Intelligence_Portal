"""PART 26.2: the joining-documents AI check flagged an experience letter ending May 2026 as "in the future" on
18 Nov 2026 - the model was never told today's date. The validator now sends it with every check."""

from datetime import date
from types import SimpleNamespace

from app.ai_services import document_validator


def test_the_document_check_is_told_todays_date(monkeypatch):
    sent = {}

    class FakeMessages:
        def parse(self, **kw):
            sent.update(kw)
            out = document_validator.DocumentValidatorOutput(doc_type_detected="experience_letter", matches_expected_type=True,
                                                             extracted_fields=document_validator.ExtractedFields(name="Asha"),
                                                             validation_status="valid", issues=[])
            return SimpleNamespace(parsed_output=out)

    monkeypatch.setattr(document_validator, "_get_client", lambda: SimpleNamespace(messages=FakeMessages()))
    result = document_validator.validate_document("experience_letter", "Asha worked here from 2018 to May 2026.")
    assert result["validation_status"] == "valid"
    assert f"Today's date: {date.today().isoformat()}" in sent["messages"][0]["content"]
