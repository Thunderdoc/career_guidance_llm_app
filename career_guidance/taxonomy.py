"""Occupation taxonomy (O*NET-derived) and skill normalisation.

The catalog is a bundled JSON snapshot built by ``scripts/build_catalog.py``.
Everything here is pure Python so it works offline and is easy to test.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "data" / "catalog" / "occupations.json"

# Canonical skill -> list of user-facing synonyms / abbreviations (lower-case).
SKILL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "python": ("py", "python3", "python 3"),
    "javascript": ("js", "es6", "ecmascript", "node", "node.js", "nodejs"),
    "typescript": ("ts",),
    "sql": ("structured query language", "mysql", "postgres", "postgresql", "sqlite", "t-sql"),
    "microsoft sql server": ("sql server", "mssql"),
    "excel": ("microsoft excel", "ms excel", "spreadsheets", "spreadsheet"),
    "power bi": ("powerbi", "microsoft power bi"),
    "tableau": ("tableau software",),
    "machine learning": ("ml",),
    "artificial intelligence": ("ai",),
    "deep learning": ("dl", "neural networks", "neural network"),
    "natural language processing": ("nlp",),
    "data visualization": ("data visualisation", "dataviz", "charts", "dashboards"),
    "statistics": ("stats", "statistical analysis"),
    "mathematics": ("math", "maths"),
    "programming": (
        "coding",
        "software development",
        "development",
        "software engineering",
        "dsa",
        "data structures",
        "algorithms",
        "oop",
    ),
    "java": ("core java", "java se", "java ee", "spring", "spring boot"),
    "c++": ("cpp", "c plus plus"),
    "c#": ("csharp", "c sharp", ".net", "dotnet", "asp.net"),
    "html": ("html5", "hypertext markup language"),
    "css": ("css3", "cascading style sheets", "tailwind", "sass", "scss"),
    "react": ("reactjs", "react.js"),
    "angular": ("angularjs",),
    "vue": ("vuejs", "vue.js"),
    "django": ("django framework",),
    "flask": ("flask framework",),
    "git": ("github", "gitlab", "version control"),
    "docker": ("containers", "containerisation", "containerization"),
    "kubernetes": ("k8s",),
    "amazon web services": ("aws", "amazon aws"),
    "microsoft azure": ("azure",),
    "google cloud platform": ("gcp", "google cloud"),
    "linux": ("ubuntu", "unix", "bash", "shell scripting", "shell"),
    "technical writing": ("documentation", "tech writing", "writing documentation"),
    "writing": ("content writing", "copywriting"),
    "communication": ("communication skills", "verbal communication", "presenting", "presentation"),
    "project management": ("pm", "agile", "scrum", "kanban"),
    "atlassian jira": ("jira",),
    "customer service": ("customer support", "client support", "support"),
    "adobe photoshop": ("photoshop",),
    "adobe illustrator": ("illustrator",),
    "figma": ("figma design",),
    "user experience": ("ux", "ux design", "user experience design"),
    "user interface": ("ui", "ui design", "user interface design"),
    "graphic design": ("graphics", "visual design"),
    "accounting": ("bookkeeping", "tally", "tally erp"),
    "finance": ("financial analysis", "financial modelling", "financial modeling"),
    "marketing": ("digital marketing", "seo", "social media marketing"),
    "sales": ("selling", "business development"),
    "teaching": ("tutoring", "instructing", "training", "mentoring"),
    "nursing": ("patient care", "clinical care", "nurse", "gnm", "bsc nursing"),
    "first aid": ("cpr", "emergency care"),
    "autodesk autocad": ("autocad", "cad"),
    "matlab": ("mat lab",),
    "r": ("r programming", "r language", "rstudio"),
    "testing": ("qa", "quality assurance", "software testing", "test automation", "selenium"),
    "troubleshooting": ("debugging", "problem solving", "problem-solving"),
    "critical thinking": ("analytical thinking", "analysis", "analytical skills"),
    "complex problem solving": ("complex problem-solving",),
    "leadership": ("team leadership", "team lead", "management"),
    "research": ("research skills", "academic research"),
    "electronics": ("electronic circuits", "circuits", "embedded", "embedded systems", "arduino"),
    "mechanical engineering": ("mechanical design", "solidworks", "catia"),
    "civil engineering": ("structural engineering", "surveying"),
    "biology": ("life sciences", "biotech", "biotechnology"),
    "chemistry": ("chemical analysis", "lab work", "laboratory"),
    "law": ("legal", "legal research"),
    "hindi": ("hindi language",),
    "tamil": ("tamil language",),
    "english": ("english language", "spoken english"),
    "physics": ("applied physics",),
    "psychology": ("counseling psychology",),
    "cooking": ("culinary", "chef", "baking"),
    "driving": ("driver", "driving licence", "driving license"),
    "agriculture": ("farming", "horticulture", "agri"),
    "public speaking": ("speaking", "oratory", "anchoring"),
    "negotiation": ("negotiating",),
    "economics": ("econ", "microeconomics", "macroeconomics"),
    "history": ("world history", "indian history"),
    "geography": ("gis", "maps"),
    "music": ("singing", "guitar", "piano", "carnatic"),
    "art": ("drawing", "painting", "sketching", "fine arts"),
    "photography": ("photo editing", "camera"),
    "video editing": ("premiere pro", "after effects", "davinci resolve", "video production"),
    "social media": ("instagram", "youtube", "content creation", "influencer"),
    "human resources": ("hr", "recruitment", "recruiting", "talent acquisition"),
    "operations": ("operations management", "ops"),
    "supply chain": ("logistics", "procurement", "warehouse"),
    "banking": ("bank", "loans", "retail banking"),
    "insurance": ("insurance sales", "underwriting"),
    "pharmacy": ("pharmacist", "pharma", "pharmaceutical"),
    "dentistry": ("dental", "dentist"),
    "physiotherapy": ("physio", "physical therapy"),
    "counselling": ("counseling", "counsellor", "counselor", "therapy"),
    "welding": ("welder", "fabrication"),
    "plumbing": ("plumber",),
    "electrical": ("electrician", "electrical engineering", "wiring", "power systems"),
    "security": ("security guard", "surveillance"),
    "cybersecurity": (
        "cyber security",
        "ethical hacking",
        "penetration testing",
        "infosec",
        "information security",
    ),
    "networking": ("computer networking", "ccna", "network administration", "tcp/ip"),
    "data entry": ("data-entry",),
    "typing": ("typewriting",),
    "administration": ("admin", "office administration", "clerical", "office work"),
    "pandas": ("numpy", "scipy", "data analysis"),
    "data science": ("data scientist",),
    "data analytics": ("analytics", "business analytics", "data analyst"),
    "cloud computing": ("cloud", "devops"),
    "mobile development": (
        "android",
        "ios",
        "flutter",
        "react native",
        "kotlin",
        "swift",
        "app development",
    ),
    "game development": ("unity", "unreal", "game design"),
    "blockchain": ("web3", "solidity", "crypto"),
    "iot": ("internet of things", "raspberry pi"),
    "robotics": ("ros", "automation"),
    "biotechnology": ("genetics", "microbiology", "molecular biology"),
    "nutrition": ("dietetics", "dietitian"),
    "hospitality": ("hotel management", "front office", "housekeeping"),
    "event management": ("events", "event planning"),
    "journalism": ("reporting", "news writing"),
    "translation": ("translator", "interpreting"),
    "fashion design": ("fashion", "tailoring", "textile design"),
    "interior design": ("interiors", "space planning"),
    "architecture": ("architectural design", "revit"),
    "real estate": ("property", "realtor"),
    "retail": ("shop", "store management", "cashier"),
    "fitness": ("gym", "personal training", "yoga"),
    "aviation": ("pilot", "cabin crew", "air hostess"),
    "automotive": ("car repair", "mechanic", "automobile"),
    "carpentry": ("woodwork", "carpenter"),
    "child care": ("childcare", "babysitting", "early childhood"),
    "social work": ("ngo", "community service", "volunteering"),
    "public policy": ("policy", "governance", "civil services", "upsc"),
    "environmental science": ("environment", "sustainability", "ecology"),
    "geology": ("earth science", "mining"),
    "astronomy": ("astrophysics", "space science"),
}

# Canonical skill -> O*NET skill/knowledge elements it implies. Lets a user's
# concrete tool ("tally") count toward the occupation's core competencies
# ("Economics and Accounting") rather than only exact tech-name matches.
DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "python": ("Programming", "Computers and Electronics"),
    "javascript": ("Programming", "Computers and Electronics"),
    "typescript": ("Programming", "Computers and Electronics"),
    "java": ("Programming", "Computers and Electronics"),
    "c++": ("Programming", "Computers and Electronics"),
    "c#": ("Programming", "Computers and Electronics"),
    "r": ("Programming", "Mathematics"),
    "sql": ("Programming", "Computers and Electronics"),
    "html": ("Programming", "Computers and Electronics", "Design"),
    "css": ("Programming", "Design"),
    "react": ("Programming",),
    "angular": ("Programming",),
    "vue": ("Programming",),
    "django": ("Programming",),
    "flask": ("Programming",),
    "git": ("Computers and Electronics",),
    "docker": ("Computers and Electronics", "Systems Analysis"),
    "kubernetes": ("Computers and Electronics", "Systems Analysis"),
    "amazon web services": ("Computers and Electronics", "Systems Analysis"),
    "microsoft azure": ("Computers and Electronics", "Systems Analysis"),
    "google cloud platform": ("Computers and Electronics", "Systems Analysis"),
    "linux": ("Computers and Electronics",),
    "programming": ("Programming", "Computers and Electronics"),
    "testing": ("Quality Control Analysis", "Programming"),
    "troubleshooting": ("Troubleshooting", "Complex Problem Solving"),
    "machine learning": ("Mathematics", "Programming", "Complex Problem Solving"),
    "artificial intelligence": ("Mathematics", "Programming"),
    "deep learning": ("Mathematics", "Programming"),
    "natural language processing": ("Programming", "English Language"),
    "statistics": ("Mathematics",),
    "mathematics": ("Mathematics",),
    "data visualization": ("Mathematics", "Computers and Electronics"),
    "excel": ("Mathematics", "Clerical"),
    "power bi": ("Mathematics", "Computers and Electronics"),
    "tableau": ("Mathematics", "Computers and Electronics"),
    "technical writing": ("Writing", "English Language"),
    "writing": ("Writing", "English Language"),
    "communication": ("Speaking", "Active Listening", "Communications and Media"),
    "english": ("English Language",),
    "hindi": ("Foreign Language",),
    "tamil": ("Foreign Language",),
    "project management": (
        "Coordination",
        "Management of Personnel Resources",
        "Administration and Management",
        "Time Management",
    ),
    "leadership": (
        "Management of Personnel Resources",
        "Coordination",
        "Administration and Management",
    ),
    "customer service": ("Service Orientation", "Customer and Personal Service"),
    "sales": ("Persuasion", "Negotiation", "Sales and Marketing"),
    "marketing": ("Sales and Marketing", "Persuasion", "Communications and Media"),
    "accounting": ("Economics and Accounting", "Mathematics", "Clerical"),
    "finance": ("Economics and Accounting", "Mathematics"),
    "teaching": ("Instructing", "Education and Training", "Learning Strategies"),
    "research": ("Science", "Critical Thinking"),
    "critical thinking": ("Critical Thinking", "Judgment and Decision Making"),
    "complex problem solving": ("Complex Problem Solving",),
    "nursing": ("Medicine and Dentistry", "Service Orientation", "Biology"),
    "first aid": ("Medicine and Dentistry", "Service Orientation"),
    "biology": ("Biology", "Science"),
    "chemistry": ("Chemistry", "Science"),
    "physics": ("Physics", "Science", "Mathematics"),
    "law": ("Law and Government",),
    "electronics": ("Computers and Electronics", "Engineering and Technology", "Troubleshooting"),
    "mechanical engineering": ("Mechanical", "Engineering and Technology", "Design", "Mathematics"),
    "civil engineering": (
        "Building and Construction",
        "Engineering and Technology",
        "Design",
        "Mathematics",
    ),
    "autodesk autocad": ("Design", "Engineering and Technology"),
    "graphic design": ("Design", "Fine Arts"),
    "user experience": ("Design", "Computers and Electronics"),
    "user interface": ("Design", "Computers and Electronics", "Programming"),
    "adobe photoshop": ("Design", "Fine Arts"),
    "adobe illustrator": ("Design", "Fine Arts"),
    "figma": ("Design",),
    "psychology": ("Psychology", "Social Perceptiveness"),
    "cooking": ("Food Production",),
    "driving": ("Transportation",),
    "agriculture": ("Food Production", "Biology"),
    "public speaking": ("Speaking", "Persuasion"),
    "negotiation": ("Negotiation", "Persuasion"),
    "economics": ("Economics and Accounting",),
    "history": ("History and Archeology",),
    "geography": ("Geography",),
    "music": ("Fine Arts",),
    "art": ("Fine Arts", "Design"),
    "photography": ("Fine Arts", "Communications and Media"),
    "video editing": ("Communications and Media", "Fine Arts"),
    "social media": ("Communications and Media", "Sales and Marketing"),
    "human resources": ("Personnel and Human Resources", "Administration and Management"),
    "operations": ("Administration and Management", "Operations Analysis"),
    "supply chain": ("Transportation", "Administration and Management"),
    "banking": ("Economics and Accounting", "Customer and Personal Service"),
    "insurance": ("Economics and Accounting", "Customer and Personal Service"),
    "pharmacy": ("Medicine and Dentistry", "Chemistry"),
    "dentistry": ("Medicine and Dentistry",),
    "physiotherapy": ("Medicine and Dentistry", "Therapy and Counseling"),
    "counselling": ("Therapy and Counseling", "Psychology", "Social Perceptiveness"),
    "welding": ("Mechanical", "Production and Processing"),
    "plumbing": ("Building and Construction", "Mechanical"),
    "electrical": ("Engineering and Technology", "Mechanical", "Physics"),
    "security": ("Public Safety and Security",),
    "cybersecurity": (
        "Computers and Electronics",
        "Public Safety and Security",
        "Telecommunications",
    ),
    "networking": ("Telecommunications", "Computers and Electronics"),
    "data entry": ("Clerical", "Computers and Electronics"),
    "typing": ("Clerical",),
    "administration": ("Clerical", "Administration and Management"),
    "pandas": ("Mathematics", "Programming"),
    "data science": ("Mathematics", "Programming", "Complex Problem Solving"),
    "data analytics": ("Mathematics", "Computers and Electronics", "Systems Analysis"),
    "cloud computing": ("Computers and Electronics", "Systems Analysis", "Telecommunications"),
    "mobile development": ("Programming", "Computers and Electronics", "Design"),
    "game development": ("Programming", "Design", "Fine Arts"),
    "blockchain": ("Programming", "Computers and Electronics"),
    "iot": ("Computers and Electronics", "Engineering and Technology", "Programming"),
    "robotics": ("Engineering and Technology", "Programming", "Mechanical"),
    "biotechnology": ("Biology", "Chemistry", "Science"),
    "nutrition": ("Biology", "Medicine and Dentistry", "Food Production"),
    "hospitality": ("Customer and Personal Service", "Service Orientation"),
    "event management": (
        "Coordination",
        "Customer and Personal Service",
        "Administration and Management",
    ),
    "journalism": ("Writing", "Communications and Media", "English Language"),
    "translation": ("Foreign Language", "English Language", "Writing"),
    "fashion design": ("Design", "Fine Arts", "Production and Processing"),
    "interior design": ("Design", "Building and Construction", "Fine Arts"),
    "architecture": ("Design", "Building and Construction", "Engineering and Technology"),
    "real estate": ("Sales and Marketing", "Customer and Personal Service", "Law and Government"),
    "retail": ("Sales and Marketing", "Customer and Personal Service"),
    "fitness": ("Education and Training", "Medicine and Dentistry", "Service Orientation"),
    "aviation": ("Transportation", "Public Safety and Security"),
    "automotive": ("Mechanical", "Repairing", "Troubleshooting"),
    "carpentry": ("Building and Construction", "Design", "Mechanical"),
    "child care": ("Education and Training", "Psychology", "Service Orientation"),
    "social work": ("Therapy and Counseling", "Sociology and Anthropology", "Service Orientation"),
    "public policy": (
        "Law and Government",
        "Sociology and Anthropology",
        "Administration and Management",
    ),
    "environmental science": ("Biology", "Chemistry", "Geography", "Science"),
    "geology": ("Geography", "Physics", "Science"),
    "astronomy": ("Physics", "Mathematics", "Science"),
}

# Reverse index synonym -> canonical
_SYNONYM_INDEX: dict[str, str] = {}
for _canon, _syns in SKILL_SYNONYMS.items():
    _SYNONYM_INDEX[_canon] = _canon
    for _s in _syns:
        _SYNONYM_INDEX[_s] = _canon

_SPLIT_RE = re.compile(r"[,\n;/•|]+|\band\b|&")
_CLEAN_RE = re.compile(r"[^a-z0-9+#.\- ]+")


@dataclass(frozen=True)
class Occupation:
    """A single occupation from the taxonomy."""

    id: str
    title: str
    description: str
    job_zone: int
    skills: list[str] = field(default_factory=list)
    knowledge: list[str] = field(default_factory=list)
    technology: list[str] = field(default_factory=list)
    hot_technology: list[str] = field(default_factory=list)
    alt_titles: list[str] = field(default_factory=list)
    holland_code: str = ""
    interests: dict[str, float] = field(default_factory=dict)
    related: list[str] = field(default_factory=list)

    @property
    def all_skill_terms(self) -> list[str]:
        """Every skill-like term describing this occupation (lower-case, de-duplicated)."""
        seen: dict[str, None] = {}
        for term in [*self.skills, *self.knowledge, *self.technology]:
            seen.setdefault(term.lower(), None)
        return list(seen)

    def document(self) -> str:
        """Text used for semantic matching."""
        parts = [
            self.title,
            self.title,  # title weight
            " ".join(self.alt_titles),
            self.description,
            " ".join(self.skills * 2),
            " ".join(self.knowledge),
            " ".join(self.technology),
            " ".join(self.hot_technology * 2),
        ]
        return " ".join(parts).lower()


def normalize_skill(raw: str) -> str:
    """Return the canonical form of a single skill string."""
    text = raw.strip().lower()
    text = _CLEAN_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        return ""
    if text in _SYNONYM_INDEX:
        return _SYNONYM_INDEX[text]
    # Strip common suffixes like "programming", "language", "skills"
    stripped = re.sub(
        r"\b(programming|language|skills?|basics|advanced|expert|beginner)\b", "", text
    )
    stripped = re.sub(r"\s+", " ", stripped).strip()
    if stripped and stripped in _SYNONYM_INDEX:
        return _SYNONYM_INDEX[stripped]
    return stripped or text


_SYNONYM_PATTERNS: list[tuple[re.Pattern[str], str]] = sorted(
    (
        (re.compile(rf"(?<![a-z0-9+#]){re.escape(syn)}(?![a-z0-9+#])"), canon)
        for syn, canon in _SYNONYM_INDEX.items()
        if len(syn) >= 2
    ),
    key=lambda pair: -len(pair[0].pattern),
)
_FILLER = {
    "need",
    "needs",
    "worked",
    "with",
    "using",
    "used",
    "on",
    "in",
    "of",
    "for",
    "the",
    "a",
    "an",
    "to",
    "experience",
    "knowledge",
    "strong",
    "good",
    "basic",
    "proficient",
    "familiar",
    "hands",
    "years",
    "year",
    "required",
    "must",
    "have",
    "plus",
    "etc",
}


def extract_skills(text: str) -> list[str]:
    """Split free text (skills box, resume, job description) into canonical skills.

    Every chunk is scanned for known synonyms; short unknown chunks that look
    like a skill name are kept verbatim so nothing the user typed is lost.
    """
    if not text:
        return []
    found: dict[str, None] = {}
    for chunk in _SPLIT_RE.split(text.lower()):
        chunk = chunk.strip()
        if not chunk:
            continue
        hit = False
        for pattern, canon in _SYNONYM_PATTERNS:
            if pattern.search(chunk):
                found.setdefault(canon, None)
                hit = True
        if hit:
            continue
        words = [w for w in re.split(r"\s+", _CLEAN_RE.sub(" ", chunk)) if w and w not in _FILLER]
        if 0 < len(words) <= 3 and len(" ".join(words)) <= 40:
            canon = normalize_skill(" ".join(words))
            if canon and canon not in _FILLER:
                found.setdefault(canon, None)
    return list(found)


class Taxonomy:
    """In-memory occupation catalog with lookup helpers."""

    def __init__(self, occupations: list[Occupation]) -> None:
        self.occupations = occupations
        self._by_id = {o.id: o for o in occupations}
        self._term_index: dict[str, str] = {}
        for occ in occupations:
            for term in occ.all_skill_terms:
                self._term_index.setdefault(normalize_skill(term), term)

    def __len__(self) -> int:
        return len(self.occupations)

    def get(self, occupation_id: str) -> Occupation | None:
        return self._by_id.get(occupation_id)

    def search(self, query: str, limit: int = 10) -> list[Occupation]:
        """Simple title / alt-title substring search."""
        q = query.strip().lower()
        if not q:
            return []
        hits = []
        for occ in self.occupations:
            if q in occ.title.lower():
                hits.append((0, occ))
            elif any(q in alt.lower() for alt in occ.alt_titles):
                hits.append((1, occ))
        hits.sort(key=lambda h: (h[0], h[1].title))
        return [occ for _, occ in hits[:limit]]

    def canonical_terms(self) -> list[str]:
        """All normalised skill terms known to the taxonomy."""
        return list(self._term_index)

    def display_term(self, canonical: str) -> str:
        """Human-readable label for a canonical skill (taxonomy casing if known)."""
        if canonical in self._term_index:
            return self._term_index[canonical]
        return canonical.title() if len(canonical) > 3 else canonical.upper()


@lru_cache(maxsize=2)
def load_taxonomy(path: str | None = None) -> Taxonomy:
    """Load (and cache) the bundled taxonomy."""
    catalog_path = Path(path) if path else _DEFAULT_CATALOG
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    return Taxonomy([Occupation(**item) for item in raw])
