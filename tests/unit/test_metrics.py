import pytest

from rebind.metrics import (
    cer,
    header_leaks,
    levenshtein,
    normalize,
    paragraph_f1,
    score,
    tokenize,
    wer,
)


def test_normalize_unifies_typography() -> None:
    assert normalize("“Quaintly : ‘I’m off’—now…”") == "\"quaintly: 'i'm off'-now...\""
    assert normalize("a  _b_\n c") == "a b c"


def test_levenshtein() -> None:
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3
    assert levenshtein(["a", "b"], ["a", "c", "b"]) == 1


def test_cer_and_wer() -> None:
    ref = "The quick brown fox jumps over the lazy dog."
    assert cer(ref, ref) == 0.0
    assert wer(ref, ref) == 0.0
    assert cer("The quick brown fax jumps over the lazy dog.", ref) == pytest.approx(1 / len(ref))
    assert wer("The quick brown fax jumps over the lazy dog.", ref) == pytest.approx(1 / 9)
    # typography differences are not errors
    assert cer("The quick brown fox jumps over the lazy dog .", ref) == 0.0
    assert tokenize("Don’t stop!") == ["don't", "stop"]


def test_cer_counts_moved_text_twice() -> None:
    a, b = "alpha beta gamma delta " * 5, "omega psi chi phi " * 5
    assert cer(b + a, a + b) > 0.5


def test_paragraph_f1() -> None:
    ref = ["one two three four", "five six seven", "eight nine ten"]
    assert paragraph_f1(ref, ref)["f1"] == 1.0
    merged = ["one two three four five six seven", "eight nine ten"]
    pf = paragraph_f1(merged, ref)
    assert pf["precision"] == 1.0
    assert pf["recall"] == pytest.approx(2 / 3)


def test_header_leaks_and_score() -> None:
    paras = ["Body DR. JEKYLL AND MR. HYDE text", "42", "Clean text."]
    assert header_leaks(paras, ["DR. JEKYLL AND MR. HYDE"]) == 2
    s = score(["Clean text."], ["Clean text."], [])
    assert s.as_dict()["cer"] == 0.0 and s.paragraph_f1 == 1.0
