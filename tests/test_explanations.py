"""Template explanations: locales, fallbacks, previews and source labels."""

from __future__ import annotations

from career_guidance.explanations import SAMPLE_VALUES, Explanations, get_explanations


def test_all_locales_ship_the_same_keys():
    engine = Explanations.load()
    english = set(engine.keys("en"))
    assert english, "no templates loaded"
    for locale in ("en", "ta", "hi"):
        assert set(engine.keys(locale)) == english, f"{locale} is missing template keys"


def test_render_fills_placeholders():
    text = get_explanations().render(
        "match.headline", locale="en", matched_count=4, total_skills=7, title="Data Analyst"
    )
    assert "4" in text and "7" in text and "Data Analyst" in text
    assert "{" not in text


def test_render_falls_back_to_english_for_unknown_locale():
    text = get_explanations().render(
        "readiness.summary", locale="fr", readiness=50, title="X", strong=1, weak=1, missing=1
    )  # noqa: E501
    assert "50" in text and "X" in text


def test_render_unknown_key_returns_the_key_not_a_crash():
    assert get_explanations().render("nope.missing", locale="en") == "nope.missing"


def test_preview_covers_every_template_key():
    preview = get_explanations().preview("ta")
    assert set(preview) == set(get_explanations().keys("ta"))
    assert all(
        value and "{" not in value or value.count("{") == value.count("}")
        for value in preview.values()
    )


def test_sample_values_match_placeholders():
    """Every placeholder used by a template is answered by the sample values."""
    import re

    engine = get_explanations()
    for key in engine.keys("en"):
        template = engine.locale_templates("en")[key]
        for placeholder in re.findall(r"\{([a-z_]+)\}", template):
            assert placeholder in SAMPLE_VALUES, f"{key} uses unknown placeholder {placeholder}"


def test_admin_overrides_take_precedence():
    engine = Explanations.load()
    engine.set_overrides({"ta": {"match.headline": "தனிப்பயன் {title}"}})
    assert (
        engine.render("match.headline", locale="ta", matched_count=1, total_skills=2, title="Z")
        == "தனிப்பயன் Z"
    )
    engine.set_overrides({})


def test_source_label_names_the_engine():
    assert "Source:" in get_explanations().source()
    assert "template" in get_explanations().source().lower()
