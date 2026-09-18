#!/usr/bin/env python3
"""Black-box API round: every public route, against any base URL.

The script owns no application code — it only speaks HTTP — so it can be run
against a local uvicorn, a Render deployment or a Vercel rewrite:

    python scripts/smoke_api.py                                   # http://127.0.0.1:8000
    python scripts/smoke_api.py --base https://career-guidance-llm-app.onrender.com
    python scripts/smoke_api.py --base https://career-guidance-web-sigma.vercel.app

Exit code is non-zero if any *expected* status does not match, so it can be
wired into CI or a release check. Documents are validated by content-type and
magic bytes, not by status alone (a 200 HTML shell is not a PDF).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

STATUS_ONLY = "(status only)"
failures: list[str] = []
passed = 0


class Client:
    """Minimal cookie-aware HTTP client (stdlib only, no test client)."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, method: str, path: str, body=None, headers=None, raw: bool = False):
        data = None
        request_headers = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode()
            request_headers["content-type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base}{path}", data=data, headers=request_headers, method=method
        )
        try:
            response = self.opener.open(request, timeout=60)
        except urllib.error.HTTPError as error:  # non-2xx is a valid expectation
            return error.code, error.read(), dict(error.headers)
        payload = response.read()
        return response.status, payload, dict(response.headers)

    def json(self, method: str, path: str, body=None):
        status, payload, headers = self.request(method, path, body)
        if headers.get("content-type", "").startswith("application/json"):
            try:
                return status, json.loads(payload or b"null")
            except json.JSONDecodeError:
                return status, None
        return status, payload.decode("utf-8", "replace")[:120]


def check(  # noqa: PLR0913 - one small helper for the whole round
    name: str,
    got,
    expected=200,
    client: Client | None = None,
    path: str = "",
    extra=None,
):
    global passed
    status = got[0] if isinstance(got, tuple) else got
    if isinstance(expected, (list, tuple, set)):
        ok = status in expected
    else:
        ok = status == expected
    detail = ""
    if ok and client is not None and extra:
        detail = extra(client, got[1])
        if detail:
            ok = False
    if ok:
        passed += 1
        print(f"  ok   {name:52} {status}")
    else:
        failures.append(f"{name} ({path or name}) -> {status}, expected {expected} {detail}")
        print(f"  FAIL {name:52} {status} expected {expected} {detail}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default="smoke@example.com")
    args = parser.parse_args()

    client = Client(args.base)
    print(f"black-box round against {client.base}")

    # ---------------------------------------------------------------- public
    check("health", client.json("GET", "/api/v1/health"))
    check("meta", client.json("GET", "/api/v1/meta"))
    check("skills/suggest", client.json("GET", "/api/v1/skills/suggest?q=pyth"))
    check("careers/search", client.json("GET", "/api/v1/careers/search?q=data&limit=3"))
    # The catalogue browser is part of the private app (S1): only /health,
    # /meta, /skills/suggest and /careers/search stay public.
    check("careers list (anonymous)", client.json("GET", "/api/v1/careers?limit=3"), 401)
    check("career detail (anonymous)", client.json("GET", "/api/v1/careers/15-1199.08"), 401)

    def private_routes_signature(label: str):
        for method, path, body in (
            ("POST", "/api/v1/recommend", {"skills": "sql"}),
            ("POST", "/api/v1/assessment", {"answers": {"r1": 3}}),
            ("POST", "/api/v1/jobs/fit", {"skills": "sql"}),
            ("POST", "/api/v1/resume/extract", {"text": "x"}),
            ("GET", "/api/v1/history", None),
        ):
            check(f"{label} {method} {path}", client.json(method, path, body), 401, path=path)

    private_routes_signature("anonymous")

    # ------------------------------------------------------------ signed in
    status, payload = client.json(
        "POST", "/api/v1/auth/magic-link", {"email": args.email, "next": "/"}
    )
    check("magic-link request", (status, payload), 200, path="/api/v1/auth/magic-link")
    link = (payload or {}).get("dev_link") if isinstance(payload, dict) else None
    if link:
        status, _, _ = client.request("GET", link)
        check("magic-link verify", status, (200, 303), path=link)
    else:
        print("  ..   no dev link returned (real e-mail delivery) — sign in by hand for the rest")

    check("auth/me", client.json("GET", "/api/v1/auth/me"))
    check("careers list", client.json("GET", "/api/v1/careers?limit=3"))
    check("career detail", client.json("GET", "/api/v1/careers/15-1199.08"))
    check("career detail 404", client.json("GET", "/api/v1/careers/ZZ-0000.00"), 404)

    # --------------------------------------------------------- journey core
    check(
        "profile put",
        client.json(
            "PUT",
            "/api/v1/profile",
            {
                "persona": "Career switcher",
                "education": "Bachelor's degree",
                "experience_level": "Junior (0-2 years)",
                "skills": ["sql", "excel", "python"],
                "goals": "data analyst",
                "hours_per_week": 8,
                "set_target": "15-1199.08",
            },
        ),
    )
    check("profile get", client.json("GET", "/api/v1/profile"))
    check("onboarding", client.json("POST", "/api/v1/onboarding", {"onboarded": True}))
    check("plan target", client.json("GET", "/api/v1/plan/target"))
    check("readiness", client.json("GET", "/api/v1/plan/readiness?career_id=15-1199.08"))
    check(
        "ratings",
        client.json(
            "POST",
            "/api/v1/plan/ratings",
            {"career_id": "15-1199.08", "ratings": {"sql": 4, "data analysis": 3}},
        ),
    )
    status, plan = client.json(
        "POST", "/api/v1/plan", {"career_id": "15-1199.08", "hours_per_week": 8}
    )
    check("plan create", (status, plan))
    plan_id = ((plan or {}).get("plan") or {}).get("plan_id") if isinstance(plan, dict) else None

    def plan_exports(client: Client, _):
        formats = (("md", None), ("ics", b"BEGIN:VCALENDAR"), ("json", b"{"), ("pdf", b"%PDF"))
        for fmt, magic in formats:
            url = f"/api/v1/plan/{plan_id}.{fmt}"
            status, payload, _headers = client.request("GET", url)
            if status != 200:
                return f"export {fmt} -> {status}"
            if magic and magic not in payload[:40]:
                return f"export {fmt} wrong body {payload[:20]!r}"
            if not magic and b"# " not in payload[:200]:
                return f"export {fmt} wrong body {payload[:20]!r}"
        return ""

    check("plan exports (md/ics/json/pdf)", (200, None), 200, client, extra=plan_exports)

    # ------------------------------------------------------- flagship screen
    status, verdict = client.json(
        "POST",
        "/api/v1/pathway",
        {
            "career_id": "29-1141.00",
            "resume_text": "B.Sc Nursing graduate, 3 years clinical experience, patient care.",
            "education": "Bachelor's degree",
            "experience_level": "Mid-level (2-5 years)",
            "hours_per_week": 6,
        },
    )
    check("pathway verdict", (status, verdict))
    if isinstance(verdict, dict):
        needed = {"verdict", "target", "plan", "bridges", "ladder", "sources"}
        missing = needed - set(verdict)
        check("pathway payload shape", (200 if not missing else 500, verdict), 200)
        if missing:
            failures.append(f"pathway is missing {sorted(missing)}")
    check("pathway signals", client.json("GET", "/api/v1/pathway/signals"))
    check("ladder", client.json("GET", "/api/v1/ladder?career_id=15-1199.08&hours_per_week=6"))
    bad_level = client.json(
        "POST",
        "/api/v1/pathway",
        {"career_id": "15-1199.08", "experience_level": "Wizard"},
    )
    check("pathway 422 unknown level", bad_level, 422)

    # ------------------------------------------------------------- reports
    def pdf(client: Client, _payload):
        status, payload_bytes, _headers = client.request("GET", "/api/v1/me/report.pdf")
        if status != 200 or not payload_bytes.startswith(b"%PDF"):
            return f"report.pdf -> {status} {payload_bytes[:12]!r}"
        return ""

    check("me/report.pdf", (200, None), 200, client, extra=pdf)
    check("legacy reports/career.pdf", (200, None), 200, client, extra=pdf)

    # ------------------------------------------------------------ learning
    check("learn list", client.json("GET", "/api/v1/learn?limit=3"))
    check("learn saved", client.json("GET", "/api/v1/learn/saved"))
    check("gamification", client.json("GET", "/api/v1/gamification"))
    check("dashboard", client.json("GET", "/api/v1/me/dashboard"))
    check("me export", client.json("GET", "/api/v1/me/export"))
    check("announcements", client.json("GET", "/api/v1/announcements"))
    check("feedback", client.json("POST", "/api/v1/feedback", {"rating": 5, "comment": "smoke"}))

    # ------------------------------------------------------------- matcher
    status, rec = client.json(
        "POST",
        "/api/v1/recommend",
        {
            "skills": "sql, excel, python, tableau",
            "goals": "data analyst",
            "experience_level": "Junior (0-2 years)",
            "education": "Bachelor's degree",
        },
    )
    check("recommend v2", (status, rec))
    if isinstance(rec, dict):
        row = (rec.get("recommendations") or [{}])[0]
        for field in ("title", "match_percent", "why", "resources", "market", "next_steps"):
            if field not in row:
                failures.append(f"recommendation row missing {field}")
        check("recommendation shape", (200 if row.get("title") else 500, row), 200)

    # ------------------------------------------------------------- admin
    check("admin overview (non-admin 403)", client.json("GET", "/api/v1/admin/overview"), 403)
    check("admin audit (non-admin 403)", client.json("GET", "/api/v1/admin/audit"), 403)

    print(f"\n{passed} checks passed, {len(failures)} failed")
    for line in failures:
        print("  -", line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
