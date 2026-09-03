"""Streamlit entry point for the Career Guidance AI platform."""

import pandas as pd
import streamlit as st

from career_guidance import __version__
from career_guidance.analytics import summarize
from career_guidance.config import configure_logging, load_settings
from career_guidance.models import CareerRecommendation, InvalidInputError
from career_guidance.profile import EXPERIENCE_LEVELS, CareerProfile
from career_guidance.resume import extract_resume_text
from career_guidance.storage import Database, runs_to_json, runs_to_markdown
from career_guidance.suggestions import (
    format_recommendations_markdown,
    generate_recommendations,
)

settings = load_settings()
logger = configure_logging(settings)

st.set_page_config(page_title="Career Guidance AI", page_icon="🎓", layout="wide")


@st.cache_resource
def get_db() -> Database:
    """Return the shared database instance."""
    return Database(settings.database_path)


def render_recommendation(index: int, rec: CareerRecommendation) -> None:
    """Render one structured recommendation card."""
    with st.container(border=True):
        title_col, badge_col = st.columns([4, 1])
        title_col.subheader(f"{index}. {rec.title}")
        badge_col.markdown(f"**{rec.suitability.title()}**")
        st.markdown(rec.match_reason)

        col_have, col_gap = st.columns(2)
        with col_have:
            st.markdown("**✅ Matching skills**")
            if rec.matching_skills:
                st.markdown("\n".join(f"- {skill}" for skill in rec.matching_skills))
            else:
                st.markdown("_None detected yet_")
        with col_gap:
            st.markdown("**📚 Skills to learn**")
            if rec.missing_skills:
                st.markdown("\n".join(f"- {skill}" for skill in rec.missing_skills))
            else:
                st.markdown("_No gaps detected_")

        with st.expander("🗺️ Learning path & next steps"):
            if rec.learning_path:
                st.markdown("**Learning path**")
                st.markdown(
                    "\n".join(
                        f"{i}. {step}" for i, step in enumerate(rec.learning_path, 1)
                    )
                )
            if rec.next_steps:
                st.markdown("**Short-term next steps**")
                st.markdown("\n".join(f"- {step}" for step in rec.next_steps))


def render_guidance_page() -> None:
    """Render the profile form and recommendation workflow."""
    st.title("🎓 Career Guidance AI")
    st.caption(f"Version {__version__} · Environment: {settings.app_env}")
    st.markdown(
        "Build your career profile and get structured, actionable career "
        "recommendations with skill-gap analysis and a learning roadmap."
    )

    if not settings.openai_api_key:
        st.info(
            "**Demo mode**: recommendations use offline skill matching against "
            "a curated career catalog. Set `OPENAI_API_KEY` to enable "
            "AI-powered analysis."
        )

    with st.form("profile_form"):
        skills = st.text_area(
            "Skills *",
            height=120,
            max_chars=settings.max_input_length,
            placeholder="e.g. Python, SQL, data visualization, technical writing...",
        )
        col_left, col_right = st.columns(2)
        with col_left:
            interests = st.text_input("Interests", placeholder="e.g. AI, education")
            education = st.text_input("Education", placeholder="e.g. B.Sc. Computer Science")
        with col_right:
            experience = st.selectbox("Experience level", EXPERIENCE_LEVELS)
            goals = st.text_input("Career goals", placeholder="e.g. become a data analyst")
        resume_file = st.file_uploader(
            "Resume (optional, .txt / .md / .pdf, max 5 MB)",
            type=["txt", "md", "pdf"],
        )
        submitted = st.form_submit_button("Get Career Recommendations", type="primary")

    if not submitted:
        return

    resume_text = ""
    if resume_file is not None:
        try:
            resume_text = extract_resume_text(resume_file.name, resume_file.getvalue())
            st.caption(f"Resume processed: {len(resume_text)} characters extracted.")
        except InvalidInputError as error:
            st.error(f"Resume could not be used: {error}")
            return

    profile = CareerProfile(
        skills=skills,
        interests=interests,
        education=education,
        experience_level=experience,
        goals=goals,
        resume_text=resume_text,
    )

    try:
        with st.spinner("Analyzing your profile..."):
            result = generate_recommendations(profile, settings)
    except InvalidInputError as error:
        st.warning(str(error))
        return
    except Exception:  # noqa: BLE001 - surface a safe message to the user
        logger.exception("Unexpected error while generating recommendations")
        st.error("Something went wrong. Please try again later.")
        return

    try:
        get_db().save_run(
            profile.to_dict(),
            result.recommendations,
            result.provider_name,
            result.is_demo,
        )
    except Exception:  # noqa: BLE001 - persistence must not break the workflow
        logger.exception("Failed to persist recommendation run")
        st.warning("Results could not be saved to history, but are shown below.")

    if result.used_fallback:
        st.warning(
            "The AI service was unavailable, so offline skill-matching "
            "results are shown instead."
        )
    st.success(f"Recommendations generated by: {result.provider_name}")

    for index, rec in enumerate(result.recommendations, start=1):
        render_recommendation(index, rec)

    st.download_button(
        "⬇️ Download as Markdown",
        data=format_recommendations_markdown(result.recommendations),
        file_name="career-recommendations.md",
        mime="text/markdown",
    )


def render_history_page() -> None:
    """Render persistent history with export options."""
    st.title("🕘 History")
    db = get_db()
    runs = db.list_runs(limit=100)

    if not runs:
        st.info("No recommendations yet. Visit **Get Recommendations** to get started.")
        return

    col_md, col_json, col_clear = st.columns(3)
    with col_md:
        st.download_button(
            "⬇️ Export Markdown",
            data=runs_to_markdown(runs),
            file_name="guidance-history.md",
            mime="text/markdown",
        )
    with col_json:
        st.download_button(
            "⬇️ Export JSON",
            data=runs_to_json(runs),
            file_name="guidance-history.json",
            mime="application/json",
        )
    with col_clear:
        if st.button("🗑️ Clear history"):
            db.clear()
            st.rerun()

    for run in runs:
        label = f"#{run.id} · {run.created_at} · {run.provider}"
        with st.expander(label):
            skills = str(run.profile.get("skills", ""))[:200]
            st.markdown(f"**Skills:** {skills}")
            for index, rec in enumerate(run.recommendations, start=1):
                st.markdown(f"{index}. **{rec.title}** – {rec.match_reason}")


def render_analytics_page() -> None:
    """Render analytics computed from real stored data."""
    st.title("📊 Analytics")
    runs = get_db().list_runs(limit=1000)

    if not runs:
        st.info("No data yet. Analytics appear after your first recommendation run.")
        return

    summary = summarize(runs)
    metric_total, metric_ai, metric_demo = st.columns(3)
    metric_total.metric("Total runs", summary.total_runs)
    metric_ai.metric("AI runs", summary.ai_runs)
    metric_demo.metric("Demo runs", summary.demo_runs)

    if summary.top_careers:
        st.markdown("#### Most recommended careers")
        careers_df = pd.DataFrame(
            summary.top_careers, columns=["career", "count"]
        ).set_index("career")
        st.bar_chart(careers_df)

    if summary.top_missing_skills:
        st.markdown("#### Most common skill gaps")
        skills_df = pd.DataFrame(
            summary.top_missing_skills, columns=["skill", "count"]
        ).set_index("skill")
        st.bar_chart(skills_df)

    if len(summary.runs_per_day) > 1:
        st.markdown("#### Runs per day")
        days_df = pd.DataFrame(
            summary.runs_per_day, columns=["day", "runs"]
        ).set_index("day")
        st.line_chart(days_df)


def render_about_page() -> None:
    """Render product information."""
    st.title("ℹ️ About")
    st.markdown(
        f"""
**Career Guidance AI** (v{__version__}) recommends career paths from your
profile: skills, interests, education, experience level, goals, and
optionally your resume.

- **AI mode**: with `OPENAI_API_KEY` configured, structured recommendations
  are generated by an LLM and validated before display.
- **Demo mode**: without a key, the app uses genuine offline skill matching
  against a curated career catalog, clearly labeled as such.
- Each recommendation includes matching skills, skill gaps, a learning
  path, and practical next steps.
- Runs are stored in a local SQLite database; History and Analytics are
  based only on this real data.

Resumes are processed in memory for text extraction; only a short excerpt
of the profile is stored with your history.
"""
    )


def main() -> None:
    """Render the Streamlit UI."""
    page = st.sidebar.radio(
        "Navigate", ["Get Recommendations", "History", "Analytics", "About"]
    )
    st.sidebar.caption(f"v{__version__} · {settings.app_env}")
    if page == "Get Recommendations":
        render_guidance_page()
    elif page == "History":
        render_history_page()
    elif page == "Analytics":
        render_analytics_page()
    else:
        render_about_page()


if __name__ == "__main__":
    main()
