from app.candidates.gender_inference import infer_gender


def test_infer_gender_confident_male_name():
    assert infer_gender("John Smith") == "male"


def test_infer_gender_confident_female_name():
    assert infer_gender("Priya Sharma") == "female"


def test_infer_gender_uses_first_name_only():
    # "Smith" alone means nothing to the detector -- the surname must never influence this.
    assert infer_gender("Jane Smith") == "female"
    assert infer_gender("John Doe") == "male"


def test_infer_gender_no_data_for_name_returns_none():
    # A name this dataset has never seen -- must fail closed to None (initials fallback),
    # never force a guess.
    assert infer_gender("Xyzabcqqq Nobody") is None


def test_infer_gender_none_for_missing_or_empty_name():
    assert infer_gender(None) is None
    assert infer_gender("") is None
    assert infer_gender("   ") is None
