from usgs_triplifier.states import States


def test_names_use_the_usgs_spellings():
    assert States.name_for("VI") == "United States Virgin Islands"
    assert States.name_for("MP") == "Commonwealth of the Northern Mariana Islands"
    assert States.name_for("XX") is None


def test_codes_are_the_inverse_of_names():
    assert States.code_for("United States Virgin Islands") == "VI"
    assert States.code_for("Commonwealth of the Northern Mariana Islands") == "MP"
    assert States.code_for("Virgin Islands") is None
    assert len(States.CODES) == len(States.NAMES)
    assert all(States.name_for(States.code_for(n)) == n for n in States.CODES)
