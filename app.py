"""Streamlit entry point for the Career Guidance AI platform."""

import html

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

st.set_page_config(
    page_title="Career Guidance AI",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------- #
# Styling
# --------------------------------------------------------------------------- #

_SUITABILITY_STYLE = {
    "beginner": ("🌱", "#DCFCE7", "#166534"),
    "intermediate": ("🚀", "#DBEAFE", "#1E40AF"),
    "advanced": ("🏆", "#F3E8FF", "#6B21A8"),
}

_CSS = """
<style>
/* Tighter top padding */
.block-container { padding-top: 2rem; padding-bottom: 3rem; }

/* Hero */
.cg-hero { padding: 0.25rem 0 0.75rem 0; }
.cg-hero h1 { font-size: 2.1rem; margin: 0 0 0.25rem 0; line-height: 1.2; }
.cg-hero p { color: #6B7280; margin: 0; font-size: 1.02rem; }

/* Pills / chips */
.cg-pill {
    display: inline-block; padding: 0.2rem 0.65rem; border-radius: 999px;
    font-size: 0.78rem; font-weight: 600; letter-spacing: 0.01em;
    white-space: nowrap;
}
.cg-chip {
    display: inline-block; margin: 0 0.35rem 0.4rem 0; padding: 0.22rem 0.6rem;
    border-radius: 8px; font-size: 0.83rem; line-height: 1.3;
}
.cg-chip-have { background: #ECFDF5; color: #065F46; border: 1px solid #A7F3D0; }
.cg-chip-gap { background: #FFF7ED; color: #9A3412; border: 1px solid #FED7AA; }
.cg-muted { color: #9CA3AF; font-style: italic; font-size: 0.88rem; }

/* Card header */
.cg-card-title { font-size: 1.25rem; font-weight: 700; margin: 0; }
.cg-card-rank {
    display: inline-flex; align-items: center; justify-content: center;
    width: 1.9rem; height: 1.9rem; border-radius: 50%; margin-right: 0.55rem;
    background: #EEF2FF; color: #4338CA; font-weight: 700; font-size: 0.9rem;
}
.cg-reason { color: #374151; margin: 0.35rem 0 0.75rem 0; }
.cg-section-label {
    font-size: 0.78rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.05em; color: #6B7280; margin-bottom: 0.4rem;
}

/* Step-by-step list */
.cg-steps { counter-reset: step; list-style: none; padding-left: 0; margin: 0; }
.cg-steps li {
    counter-increment: step; position: relative; padding-left: 2.2rem;
    margin-bottom: 0.55rem; line-height: 1.45;
}
.cg-steps li::before {
    content: counter(step); position: absolute; left: 0; top: 0.05rem;
    width: 1.5rem; height: 1.5rem; border-radius: 50%; background: #4F46E5;
    color: white; font-size: 0.75rem; font-weight: 700;
    display: flex; align-items: center; justify-content: center;
}

/* Sidebar */
section[data-testid="stSidebar"] .cg-brand { font-size: 1.35rem; font-weight: 800; }
section[data-testid="stSidebar"] .cg-brand-sub { color: #6B7280; font-size: 0.85rem; }

/* Metric cards */
div[data-testid="stMetric"] {
    background: #F5F6FA; border-radius: 12px; padding: 0.9rem 1rem;
}
</style>
"""


def inject_css() -> None:
    """Inject the shared stylesheet once per render."""
    st.markdown(_CSS, unsafe_allow_html=True)


def pill(text: str, bg: str, fg: str) -> str:
    """Return HTML for a small coloured pill."""
    return f'<span class="cg-pill" style="background:{bg};color:{fg};">{html.escape(text)}</span>'


def chips(items: list[str], kind: str, empty_text: str) -> str:
    """Return HTML for a group of chips or a muted placeholder."""
    if not items:
        return f'<span class="cg-muted">{html.escape(empty_text)}</span>'
    return "".join(
        f'<span class="cg-chip cg-chip-{kind}">{html.escape(item)}</span>' for item in items
    )


def steps_html(items: list[str]) -> str:
    """Return HTML for a numbered step list."""
    return (
        '<ol class="cg-steps">'
        + "".join(f"<li>{html.escape(item)}</li>" for item in items)
        + "</ol>"
    )


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

EXAMPLE_PROFILE = {
    "skills": (
        "Python, SQL, pandas, data visualization, Excel, statistics, "
        "technical writing, presenting to stakeholders"
    ),
    "interests": "AI, analytics, education technology",
    "education": "B.Sc. Computer Science",
    "experience": EXPERIENCE_LEVELS[1],
    "goals": "Become a data analyst and grow into a data science role",
}


@st.cache_resource
def get_db() -> Database:
    """Return the shared database instance."""
    return Database(settings.database_path)


def is_ai_mode() -> bool:
    """Whether AI recommendations are configured."""
    return bool(settings.openai_api_key)


def render_sidebar() -> str:
    """Render sidebar navigation and status; return the selected page."""
    with st.sidebar:
        st.markdown('<div class="cg-brand">🎓 Career Guidance AI</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="cg-brand-sub">Skill-gap analysis & learning roadmaps</div>',
            unsafe_allow_html=True,
        )
        st.markdown("")
        page = st.radio(
            "Navigate",
            ["✨ Get Recommendations", "🕘 History", "📊 Analytics", "ℹ️ About"],
            label_visibility="collapsed",
        )
        st.divider()

        if is_ai_mode():
            st.markdown(pill("🤖 AI mode", "#DBEAFE", "#1E40AF"), unsafe_allow_html=True)
            st.caption("Recommendations are generated by an LLM and schema-validated.")
        else:
            st.markdown(pill("🧪 Demo mode", "#FEF3C7", "#92400E"), unsafe_allow_html=True)
            st.caption(
                "Offline keyword matching against a curated catalog. "
                "Set `OPENAI_API_KEY` to enable AI analysis."
            )

        try:
            run_count = len(get_db().list_runs(limit=1000))
            st.caption(f"Saved runs: **{run_count}**")
        except Exception:  # noqa: BLE001 - sidebar must never crash the app
            pass

        st.divider()
        st.caption(f"v{__version__} · {settings.app_env}")
    return page


# --------------------------------------------------------------------------- #
# Recommendation card
# --------------------------------------------------------------------------- #


def render_recommendation(index: int, rec: CareerRecommendation) -> None:
    """Render one structured recommendation card."""
    icon, bg, fg = _SUITABILITY_STYLE.get(rec.suitability.lower(), ("🎯", "#F3F4F6", "#374151"))
    total = len(rec.matching_skills) + len(rec.missing_skills)
    coverage = len(rec.matching_skills) / total if total else 0.0

    with st.container(border=True):
        title_col, badge_col = st.columns([5, 1.4])
        with title_col:
            st.markdown(
                f'<p class="cg-card-title"><span class="cg-card-rank">{index}</span>'
                f"{html.escape(rec.title)}</p>",
                unsafe_allow_html=True,
            )
        with badge_col:
            st.markdown(
                f'<div style="text-align:right;margin-top:0.25rem;">'
                f"{pill(f'{icon} {rec.suitability.title()}', bg, fg)}</div>",
                unsafe_allow_html=True,
            )
        st.markdown(
            f'<p class="cg-reason">{html.escape(rec.match_reason)}</p>',
            unsafe_allow_html=True,
        )

        if total:
            st.progress(
                coverage,
                text=(
                    f"Skill coverage: {len(rec.matching_skills)} of {total} "
                    f"key skills ({coverage:.0%})"
                ),
            )

        col_have, col_gap = st.columns(2)
        with col_have:
            st.markdown(
                '<div class="cg-section-label">✅ You already have</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                chips(rec.matching_skills, "have", "No matching skills detected yet"),
                unsafe_allow_html=True,
            )
        with col_gap:
            st.markdown(
                '<div class="cg-section-label">📚 Skills to learn</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                chips(rec.missing_skills, "gap", "No gaps detected"),
                unsafe_allow_html=True,
            )

        if rec.learning_path or rec.next_steps:
            with st.expander("🗺️ Learning path & next steps"):
                tab_path, tab_next = st.tabs(["Learning path", "Short-term next steps"])
                with tab_path:
                    if rec.learning_path:
                        st.markdown(steps_html(rec.learning_path), unsafe_allow_html=True)
                    else:
                        st.caption("No learning path provided.")
                with tab_next:
                    if rec.next_steps:
                        st.markdown("\n".join(f"- {step}" for step in rec.next_steps))
                    else:
                        st.caption("No next steps provided.")


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #


def _apply_example_profile() -> None:
    st.session_state["skills"] = EXAMPLE_PROFILE["skills"]
    st.session_state["interests"] = EXAMPLE_PROFILE["interests"]
    st.session_state["education"] = EXAMPLE_PROFILE["education"]
    st.session_state["experience"] = EXAMPLE_PROFILE["experience"]
    st.session_state["goals"] = EXAMPLE_PROFILE["goals"]


def _clear_profile() -> None:
    for key in ("skills", "interests", "education", "goals"):
        st.session_state[key] = ""
    st.session_state["experience"] = EXPERIENCE_LEVELS[0]
    st.session_state.pop("last_result", None)


def render_guidance_page() -> None:
    """Render the profile form and recommendation workflow."""
    st.markdown(
        """
<div class="cg-hero">
  <h1>Find your next career move</h1>
  <p>Tell us what you know and where you want to go. We'll suggest five career
  paths, show which skills you already have, what's missing, and how to close the gap.</p>
</div>
""",
        unsafe_allow_html=True,
    )

    form_col, side_col = st.columns([1.6, 1], gap="large")

    with side_col:
        with st.container(border=True):
            st.markdown("**How it works**")
            st.markdown(
                """
1. **Describe yourself** — skills are required; everything else sharpens the results.
2. **Optionally upload a resume** — we extract text in memory to enrich your profile.
3. **Review 5 career paths** — each with matching skills, gaps, a learning path and next steps.
"""
            )
            st.markdown("**Tips for better results**")
            st.markdown(
                """
- List concrete tools and techniques, not just job titles.
- Separate skills with commas.
- Mention a goal so recommendations can be oriented toward it.
"""
            )
        quick_a, quick_b = st.columns(2)
        quick_a.button(
            "✨ Try an example",
            on_click=_apply_example_profile,
            use_container_width=True,
            help="Fill the form with a sample profile",
        )
        quick_b.button(
            "🧹 Clear form",
            on_click=_clear_profile,
            use_container_width=True,
        )

    with form_col:
        with st.form("profile_form", border=True):
            st.markdown("#### Your profile")
            skills = st.text_area(
                "Skills *",
                key="skills",
                height=120,
                max_chars=settings.max_input_length,
                placeholder="e.g. Python, SQL, data visualization, technical writing...",
                help="Required. Comma-separated works best.",
            )
            col_left, col_right = st.columns(2)
            with col_left:
                interests = st.text_input(
                    "Interests", key="interests", placeholder="e.g. AI, education"
                )
                education = st.text_input(
                    "Education", key="education", placeholder="e.g. B.Sc. Computer Science"
                )
            with col_right:
                experience = st.selectbox("Experience level", EXPERIENCE_LEVELS, key="experience")
                goals = st.text_input(
                    "Career goals", key="goals", placeholder="e.g. become a data analyst"
                )
            resume_file = st.file_uploader(
                "Resume (optional)",
                type=["txt", "md", "pdf"],
                help=".txt, .md or .pdf · max 5 MB · processed in memory only",
            )
            submitted = st.form_submit_button(
                "🚀 Get Career Recommendations",
                type="primary",
                use_container_width=True,
            )

    if submitted:
        _run_recommendations(skills, interests, education, experience, goals, resume_file)

    result = st.session_state.get("last_result")
    if result is None:
        return

    st.divider()
    _render_results(result)


def _run_recommendations(skills, interests, education, experience, goals, resume_file) -> None:
    """Validate input, run the provider and cache the result in session state."""
    if not skills.strip() and resume_file is None:
        st.warning("Please enter your skills or upload a resume to get started.")
        return

    resume_text = ""
    if resume_file is not None:
        try:
            resume_text = extract_resume_text(resume_file.name, resume_file.getvalue())
            st.toast(f"Resume processed · {len(resume_text):,} characters extracted", icon="📄")
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
        with st.spinner("Analyzing your profile and matching career paths..."):
            result = generate_recommendations(profile, settings)
    except InvalidInputError as error:
        st.warning(str(error))
        return
    except Exception:  # noqa: BLE001 - surface a safe message to the user
        logger.exception("Unexpected error while generating recommendations")
        st.error("Something went wrong. Please try again later.")
        return

    saved = True
    try:
        get_db().save_run(
            profile.to_dict(),
            result.recommendations,
            result.provider_name,
            result.is_demo,
        )
    except Exception:  # noqa: BLE001 - persistence must not break the workflow
        logger.exception("Failed to persist recommendation run")
        saved = False

    st.session_state["last_result"] = {
        "recommendations": result.recommendations,
        "provider_name": result.provider_name,
        "is_demo": result.is_demo,
        "used_fallback": result.used_fallback,
        "saved": saved,
    }


def _render_results(result: dict) -> None:
    recs: list[CareerRecommendation] = result["recommendations"]

    head_col, dl_col = st.columns([3, 1])
    with head_col:
        st.markdown(f"### Your top {len(recs)} career matches")
        mode = "demo" if result["is_demo"] else "AI"
        st.caption(f"Generated by **{result['provider_name']}** ({mode} mode)")
    with dl_col:
        st.download_button(
            "⬇️ Download report (.md)",
            data=format_recommendations_markdown(recs),
            file_name="career-recommendations.md",
            mime="text/markdown",
            use_container_width=True,
        )

    if result["used_fallback"]:
        st.warning(
            "The AI service was unavailable, so offline skill-matching results are shown instead."
        )
    if not result["saved"]:
        st.warning("Results could not be saved to history, but are shown below.")

    if not recs:
        st.info("No matches found. Try adding more specific skills.")
        return

    # Summary metrics
    all_gaps = [s for r in recs for s in r.missing_skills]
    unique_gaps = sorted({s.strip().lower() for s in all_gaps})

    def _fit(r: CareerRecommendation) -> float:
        return len(r.matching_skills) / max(1, len(r.matching_skills) + len(r.missing_skills))

    best = max(recs, key=_fit)
    m1, m2, m3 = st.columns(3)
    m1.metric("Career paths", len(recs))
    m2.metric("Best skill fit", best.title)
    m3.metric("Distinct skills to learn", len(unique_gaps))

    st.markdown("")
    for index, rec in enumerate(recs, start=1):
        render_recommendation(index, rec)


def render_history_page() -> None:
    """Render persistent history with export options."""
    st.markdown(
        '<div class="cg-hero"><h1>🕘 History</h1>'
        "<p>Every recommendation run is saved locally. Export or clear it any time.</p></div>",
        unsafe_allow_html=True,
    )
    db = get_db()
    runs = db.list_runs(limit=100)

    if not runs:
        st.info("No recommendations yet. Head to **✨ Get Recommendations** to get started.")
        return

    col_md, col_json, col_spacer, col_clear = st.columns([1, 1, 2, 1])
    with col_md:
        st.download_button(
            "⬇️ Export Markdown",
            data=runs_to_markdown(runs),
            file_name="guidance-history.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with col_json:
        st.download_button(
            "⬇️ Export JSON",
            data=runs_to_json(runs),
            file_name="guidance-history.json",
            mime="application/json",
            use_container_width=True,
        )
    with col_clear:
        if st.session_state.get("confirm_clear"):
            if st.button("⚠️ Confirm clear", type="primary", use_container_width=True):
                db.clear()
                st.session_state["confirm_clear"] = False
                st.session_state.pop("last_result", None)
                st.toast("History cleared", icon="🗑️")
                st.rerun()
            if st.button("Cancel", use_container_width=True):
                st.session_state["confirm_clear"] = False
                st.rerun()
        else:
            if st.button("🗑️ Clear history", use_container_width=True):
                st.session_state["confirm_clear"] = True
                st.rerun()

    st.caption(f"Showing {len(runs)} most recent run(s)")

    for run in runs:
        when = run.created_at.replace("T", " ")[:16]
        mode = "Demo" if run.is_demo else "AI"
        top = run.recommendations[0].title if run.recommendations else "—"
        label = f"#{run.id} · {when} · {mode} · Top match: {top}"
        with st.expander(label):
            skills = str(run.profile.get("skills", ""))
            goals = str(run.profile.get("goals", ""))
            level = str(run.profile.get("experience_level", ""))
            info_a, info_b = st.columns([2, 1])
            with info_a:
                st.markdown(f"**Skills:** {skills[:300]}{'…' if len(skills) > 300 else ''}")
                if goals:
                    st.markdown(f"**Goals:** {goals}")
            with info_b:
                if level:
                    st.markdown(f"**Experience:** {level}")
                st.markdown(f"**Provider:** {run.provider}")
            st.markdown("**Recommendations**")
            for index, rec in enumerate(run.recommendations, start=1):
                icon, bg, fg = _SUITABILITY_STYLE.get(
                    rec.suitability.lower(), ("🎯", "#F3F4F6", "#374151")
                )
                st.markdown(
                    f"{index}. **{html.escape(rec.title)}** "
                    f"{pill(f'{icon} {rec.suitability.title()}', bg, fg)}"
                    f"<br/><span style='color:#4B5563'>{html.escape(rec.match_reason)}</span>",
                    unsafe_allow_html=True,
                )


def render_analytics_page() -> None:
    """Render analytics computed from real stored data."""
    st.markdown(
        '<div class="cg-hero"><h1>📊 Analytics</h1>'
        "<p>Real metrics computed from your saved runs — nothing is fabricated.</p></div>",
        unsafe_allow_html=True,
    )
    runs = get_db().list_runs(limit=1000)

    if not runs:
        st.info("No data yet. Analytics appear after your first recommendation run.")
        return

    summary = summarize(runs)
    metric_total, metric_ai, metric_demo, metric_days = st.columns(4)
    metric_total.metric("Total runs", summary.total_runs)
    metric_ai.metric("AI runs", summary.ai_runs)
    metric_demo.metric("Demo runs", summary.demo_runs)
    metric_days.metric("Active days", len(summary.runs_per_day))

    st.markdown("")
    chart_left, chart_right = st.columns(2, gap="large")

    with chart_left:
        st.markdown("#### 🏅 Most recommended careers")
        if summary.top_careers:
            careers_df = pd.DataFrame(
                summary.top_careers, columns=["Career", "Times recommended"]
            ).set_index("Career")
            st.bar_chart(careers_df, horizontal=True, color="#4F46E5")
        else:
            st.caption("No data.")

    with chart_right:
        st.markdown("#### 📚 Most common skill gaps")
        if summary.top_missing_skills:
            skills_df = pd.DataFrame(
                summary.top_missing_skills, columns=["Skill", "Occurrences"]
            ).set_index("Skill")
            st.bar_chart(skills_df, horizontal=True, color="#F59E0B")
        else:
            st.caption("No data.")

    st.markdown("#### 📅 Runs per day")
    if len(summary.runs_per_day) > 1:
        days_df = pd.DataFrame(summary.runs_per_day, columns=["Day", "Runs"]).set_index("Day")
        st.line_chart(days_df, color="#4F46E5")
    else:
        st.caption("The trend chart appears once you have runs on more than one day.")


def render_about_page() -> None:
    """Render product information."""
    st.markdown(
        '<div class="cg-hero"><h1>ℹ️ About</h1>'
        f"<p>Career Guidance AI · version {__version__}</p></div>",
        unsafe_allow_html=True,
    )
    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        with st.container(border=True):
            st.markdown("#### What it does")
            st.markdown(
                """
Recommends career paths from your profile — skills, interests, education,
experience level, goals, and optionally your resume.

Each recommendation includes:
- **Matching skills** you already have
- **Skill gaps** to close
- An ordered **learning path**
- Practical **short-term next steps**
"""
            )
    with col_b:
        with st.container(border=True):
            st.markdown("#### Modes")
            st.markdown(
                """
- **🤖 AI mode** — with `OPENAI_API_KEY` configured, structured
  recommendations are generated by an LLM and validated before display.
- **🧪 Demo mode** — without a key, the app uses genuine offline skill
  matching against a curated career catalog, clearly labeled as such.
  If the AI service fails, the app falls back automatically and tells you.
"""
            )
    with st.container(border=True):
        st.markdown("#### Privacy")
        st.markdown(
            """
Resumes are processed in memory for text extraction only. Runs are stored in a
local SQLite database, and only a short excerpt of the profile is saved with
your history. **History** and **Analytics** are based solely on this real data.
"""
        )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> None:
    """Render the Streamlit UI."""
    inject_css()
    page = render_sidebar()
    if page.endswith("Get Recommendations"):
        render_guidance_page()
    elif page.endswith("History"):
        render_history_page()
    elif page.endswith("Analytics"):
        render_analytics_page()
    else:
        render_about_page()


if __name__ == "__main__":
    main()
