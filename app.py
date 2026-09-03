"""Streamlit entry point for the Career Guidance App."""

import streamlit as st

from career_guidance import __version__
from career_guidance.config import configure_logging, load_settings
from career_guidance.suggestions import (
    InvalidInputError,
    format_suggestions_markdown,
    get_career_suggestions,
)

settings = load_settings()
logger = configure_logging(settings)


def main() -> None:
    """Render the Streamlit UI."""
    st.set_page_config(page_title="Career Guidance AI App", page_icon="🎓")
    st.title("🎓 Career Guidance AI App")
    st.caption(f"Version {__version__} · Environment: {settings.app_env}")
    st.markdown(
        "This app suggests career paths based on your skills, resume summary, "
        "or interests."
    )

    skills_input = st.text_area(
        "Paste your skills, resume summary, or interests here:",
        max_chars=settings.max_input_length,
    )

    if st.button("Suggest Career Paths"):
        try:
            suggestions = get_career_suggestions(skills_input, settings)
        except InvalidInputError as error:
            st.warning(str(error))
        except Exception:  # noqa: BLE001 - surface a safe message to the user
            logger.exception("Unexpected error while generating suggestions")
            st.error("Something went wrong. Please try again later.")
        else:
            st.success("Here are your career suggestions:")
            st.markdown(format_suggestions_markdown(suggestions))


if __name__ == "__main__":
    main()
