"""Server-side PDF report: “Career Guidance Report”.

Rendered with **reportlab** (pure Python, installs cleanly in the Docker image —
WeasyPrint needs native GTK libraries that would bloat the Render free tier).
The report contains the profile summary, Holland code, top matches, skill gaps
and the week-by-week roadmap, each with its source label.
"""

from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ACCENT = colors.HexColor("#0f766e")
INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#e5e7eb")

_styles = getSampleStyleSheet()
TITLE = ParagraphStyle(
    "title",
    parent=_styles["Title"],
    fontName="Helvetica-Bold",
    fontSize=22,
    textColor=INK,
    alignment=TA_LEFT,
    spaceAfter=4,
)  # noqa: E501
SUB = ParagraphStyle("sub", parent=_styles["Normal"], fontSize=9.5, textColor=MUTED, spaceAfter=10)
H2 = ParagraphStyle(
    "h2",
    parent=_styles["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=13,
    textColor=ACCENT,
    spaceBefore=12,
    spaceAfter=6,
)  # noqa: E501
BODY = ParagraphStyle("body", parent=_styles["Normal"], fontSize=10, leading=14, textColor=INK)
SMALL = ParagraphStyle(
    "small", parent=_styles["Normal"], fontSize=8, textColor=MUTED, spaceBefore=2
)
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=10, bulletIndent=2)


def _table(rows: list[list[str]], widths: list[float] | None = None) -> Table:
    table = Table(rows, colWidths=widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def build_report(payload: dict) -> bytes:
    """Render the guidance report PDF and return its bytes.

    ``payload`` keys: ``user``, ``profile``, ``assessment``, ``matches``,
    ``readiness``, ``roadmap``, ``language``.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title="Career Guidance Report",
        author="Career Guidance AI",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    story: list = []
    user = payload.get("user") or {}
    profile = payload.get("profile") or {}
    assessment = payload.get("assessment") or {}
    matches = payload.get("matches") or []
    readiness = payload.get("readiness") or {}
    roadmap = payload.get("roadmap") or {}

    story.append(Paragraph("Career Guidance Report", TITLE))
    story.append(
        Paragraph(
            f"Prepared for <b>{_escape(user.get('name') or user.get('email') or 'you')}</b> · "
            f"{date.today():%d %b %Y} · Career Guidance AI",
            SUB,
        )
    )

    # ---- profile ----
    story.append(Paragraph("Your profile", H2))
    rows = [["Field", "Value"]]
    for label, value in (
        ("Persona", profile.get("persona")),
        ("Education", profile.get("education")),
        ("Current role", profile.get("current_role")),
        ("Experience", profile.get("experience_level")),
        ("Skills", ", ".join(profile.get("skills") or [])[:400]),
        ("Goal", profile.get("goals")),
        ("Study time", f"{profile.get('hours_per_week', 6)} hours / week"),
    ):
        if value:
            rows.append([str(label), _escape(str(value))])
    story.append(_table(rows, [40 * mm, 120 * mm]))
    story.append(Paragraph("Source: your onboarding answers and settings.", SMALL))

    # ---- interests ----
    if assessment:
        story.append(Paragraph("Interest profile (RIASEC)", H2))
        story.append(
            Paragraph(
                f"Holland code: <b>{_escape(assessment.get('holland_code', ''))}</b>",
                BODY,
            )
        )
        story.append(Spacer(1, 4))
        rows = [["Type", "Score (1–7)", "What it means"]]
        for row in assessment.get("profile") or []:
            rows.append([f"{row['name']} ({row['dim']})", f"{row['score']}", _escape(row["blurb"])])
        story.append(_table(rows, [38 * mm, 24 * mm, 98 * mm]))
        story.append(Paragraph("Source: 36-item RIASEC inventory bundled with the app.", SMALL))

    # ---- matches ----
    if matches:
        story.append(Paragraph("Top career matches", H2))
        rows = [["#", "Career", "Match", "Readiness", "Why it fits"]]
        for index, match in enumerate(matches[:5], start=1):
            rows.append(
                [
                    str(index),
                    _escape(match.get("title", "")),
                    f"{match.get('match_percent', 0)}%",
                    f"{match.get('readiness', 0)}%",
                    _escape(" ".join(match.get("why") or [])[:220]),
                ]
            )
        story.append(_table(rows, [8 * mm, 42 * mm, 18 * mm, 20 * mm, 72 * mm]))
        story.append(
            Paragraph(
                "Source: skill overlap (O*NET), interest fit and job-zone fit — weights "
                "skills 0.55 / interests 0.30 / job zone 0.15.",
                SMALL,
            )
        )
        for match in matches[:3]:
            story.append(Paragraph(f"<b>{_escape(match.get('title', ''))}</b>", BODY))
            for line in match.get("why") or []:
                story.append(Paragraph(f"• {_escape(line)}", BULLET))
            if match.get("missing_skills"):
                story.append(
                    Paragraph("To learn: " + _escape(", ".join(match["missing_skills"][:6])), SMALL)
                )

    # ---- readiness & roadmap ----
    if readiness or roadmap:
        story.append(PageBreak())
        story.append(Paragraph("Skill gap & readiness", H2))
        if readiness:
            story.append(
                Paragraph(
                    f"Target: <b>{_escape(readiness.get('title', ''))}</b> · Readiness "
                    f"<b>{readiness.get('readiness', 0)}%</b> "
                    f"({(readiness.get('counts') or {}).get('strong', 0)} strong, "
                    f"{(readiness.get('counts') or {}).get('weak', 0)} weak, "
                    f"{(readiness.get('counts') or {}).get('missing', 0)} missing)",
                    BODY,
                )
            )
        rows = [["Skill", "Importance", "Your rating", "Status"]]
        for row in (readiness.get("skills") or [])[:14]:
            rows.append(
                [
                    _escape(row["skill"]),
                    f"{row.get('importance_10', 0)}/10",
                    f"{row.get('rating', 0)}/5",
                    str(row.get("status", "")).title(),
                ]
            )
        if len(rows) > 1:
            story.append(_table(rows, [70 * mm, 28 * mm, 28 * mm, 34 * mm]))
        story.append(
            Paragraph(
                "Readiness is importance-weighted: Σ(importance × level) / Σ(importance), "
                "with strong = 1.0, weak = 0.5, missing = 0.",
                SMALL,
            )
        )

    if roadmap:
        story.append(Paragraph("Your learning roadmap", H2))
        story.append(
            Paragraph(
                f"{roadmap.get('hours_per_week', 6)} hours/week · {roadmap.get('weeks', 0)} weeks · "  # noqa: E501
                f"finish by <b>{_escape(str(roadmap.get('eta', '')))}</b> · readiness "
                f"{roadmap.get('readiness_before', 0)}% → {roadmap.get('readiness_after', 0)}%",
                BODY,
            )
        )
        rows = [["Week", "Skill", "Hours", "Status", "Free resources"]]
        for item in (roadmap.get("items") or [])[:24]:
            resources = "; ".join(
                f"{r.get('provider', '')}: {r.get('title', '')}"
                for r in (item.get("resources") or [])[:2]
            )
            rows.append(
                [
                    str(item.get("week", 1)),
                    _escape(item.get("skill", "")),
                    f"{item.get('hours', 0)}",
                    str(item.get("status", "")),
                    _escape(resources[:150]),
                ]
            )
        story.append(_table(rows, [12 * mm, 42 * mm, 14 * mm, 20 * mm, 72 * mm]))
        story.append(Paragraph(_escape(roadmap.get("source", "")), SMALL))

    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "Generated offline by Career Guidance AI from the bundled O*NET catalog, your "
            "self-ratings and curated free courses. No external service was called.",
            SMALL,
        )
    )
    doc.build(story)
    return buffer.getvalue()


def build_roadmap_pdf(roadmap: dict) -> bytes:
    """Standalone roadmap export (used by /plan → Export → PDF)."""
    return build_report({"roadmap": roadmap, "matches": []})


def _escape(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
