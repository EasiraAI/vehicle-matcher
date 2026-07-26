from vehicle_matcher.normalizer import normalize


def test_lowercases_and_splits():
    assert normalize("Toyota Camry Hybrid") == ["toyota", "camry", "hybrid"]


def test_preserves_intra_token_slash_and_hyphen():
    assert normalize("Amrok h/line 4x4") == ["amrok", "h/line", "4x4"]
    assert normalize("R-Line Tiguan") == ["r-line", "tiguan"]


def test_strips_other_punctuation():
    assert normalize("(It's actually a Toyota!)") == ["it", "s", "actually", "a", "toyota"]


def test_strips_edge_punctuation():
    assert normalize("golf- /tiguan/") == ["golf", "tiguan"]


def test_collapses_whitespace_and_empty():
    assert normalize("  Golf\t GTI  ") == ["golf", "gti"]
    assert normalize("") == []
    assert normalize("!!! ???") == []


def test_idempotent():
    once = normalize("VW Tiguan 162TSI Allspace")
    assert normalize(" ".join(once)) == once
