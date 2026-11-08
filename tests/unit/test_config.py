from pathlib import Path

import pytest

from rebind.config import PROFILES, Config, deep_merge, load_config
from rebind.errors import RebindError


def test_defaults_without_file(tmp_path: Path) -> None:
    cfg = load_config(search_dir=tmp_path)
    assert cfg.profile == "novel"
    assert cfg.dpi == 300
    assert cfg.engine == "docling"
    assert cfg.validate_.epubcheck is True
    # novel preset applied
    assert cfg.ocr.tables is False
    assert cfg.cleanup.footnotes is False


def test_file_overrides_profile_and_cli_overrides_file(tmp_path: Path) -> None:
    (tmp_path / "rebind.toml").write_text(
        'profile = "academic"\ndpi = 400\n[metadata]\ntitle = "From file"\n'
        "[build]\ntoc_depth = 1\n[validate]\nfail_on_error = false\n"
    )
    cfg = load_config(overrides={"dpi": 200, "metadata": {"authors": ["A"]}}, search_dir=tmp_path)
    assert cfg.profile == "academic"
    assert cfg.dpi == 200  # CLI wins
    assert cfg.metadata.title == "From file"
    assert cfg.metadata.authors == ["A"]
    assert cfg.build.toc_depth == 1  # file beats profile preset (academic sets 3)
    assert cfg.ocr.tables is True  # from academic preset
    assert cfg.validate_.fail_on_error is False


def test_cli_profile_beats_file_profile(tmp_path: Path) -> None:
    (tmp_path / "rebind.toml").write_text('profile = "academic"\n')
    cfg = load_config(overrides={"profile": "novel"}, search_dir=tmp_path)
    assert cfg.profile == "novel"
    assert cfg.build.toc_depth == 1  # novel preset


def test_none_overrides_are_ignored(tmp_path: Path) -> None:
    cfg = load_config(overrides={"dpi": None, "engine": None}, search_dir=tmp_path)
    assert cfg.dpi == 300


def test_unknown_profile(tmp_path: Path) -> None:
    with pytest.raises(RebindError, match="Unknown profile"):
        load_config(overrides={"profile": "comic"}, search_dir=tmp_path)


def test_unknown_key_rejected(tmp_path: Path) -> None:
    (tmp_path / "rebind.toml").write_text("[cleanup]\nhyphenate = true\n")
    with pytest.raises(RebindError, match="Invalid configuration"):
        load_config(search_dir=tmp_path)


def test_bad_toml(tmp_path: Path) -> None:
    (tmp_path / "rebind.toml").write_text("dpi = = 3")
    with pytest.raises(RebindError, match="invalid TOML"):
        load_config(search_dir=tmp_path)


def test_explicit_missing_file() -> None:
    with pytest.raises(RebindError, match="not found"):
        load_config(Path("/nonexistent/rebind.toml"))


def test_fingerprint_is_stable_and_scoped() -> None:
    a = Config()
    b = Config()
    assert a.fingerprint("dpi", "preprocess") == b.fingerprint("dpi", "preprocess")
    b.metadata.title = "changed"
    assert a.fingerprint("dpi", "preprocess") == b.fingerprint("dpi", "preprocess")
    assert a.fingerprint("metadata") != b.fingerprint("metadata")


def test_ocr_languages_fall_back_to_metadata() -> None:
    cfg = Config.model_validate({"metadata": {"language": "de"}})
    assert cfg.ocr_languages() == ["de"]
    cfg = Config.model_validate({"metadata": {"language": "de"}, "ocr": {"languages": ["fr"]}})
    assert cfg.ocr_languages() == ["fr"]


def test_example_config_is_valid() -> None:
    example = Path(__file__).parents[2] / "rebind.example.toml"
    cfg = load_config(example)
    assert cfg.profile in PROFILES


def test_deep_merge() -> None:
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"c": 3}, "d": 4}) == {
        "a": {"b": 1, "c": 3},
        "d": 4,
    }


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_to_toml_round_trips(profile: str, tmp_path: Path) -> None:
    from rebind.config import to_toml

    cfg = load_config(overrides={"profile": profile}, search_dir=tmp_path)
    path = tmp_path / "rebind.toml"
    path.write_text(to_toml(cfg))
    assert load_config(path) == cfg


def test_profiles_differ_and_are_documented() -> None:
    from rebind.config import PROFILE_HELP

    assert set(PROFILE_HELP) == set(PROFILES)
    dumps = {
        p: load_config(overrides={"profile": p}).model_dump(exclude={"profile"}) for p in PROFILES
    }
    assert len({repr(d) for d in dumps.values()}) == len(PROFILES)


def test_models_dir_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REBIND_MODELS_DIR", str(tmp_path / "m"))
    assert load_config(search_dir=tmp_path).models_dir == tmp_path / "m"
    explicit = load_config(overrides={"models_dir": tmp_path / "x"}, search_dir=tmp_path)
    assert explicit.models_dir == tmp_path / "x"
