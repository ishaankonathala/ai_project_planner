"""
core/classifier.py
──────────────────
Keyword-based project type classifier.

Supported types:
    - Construction
    - Software / IT
    - ERP / SAP
    - AI / Data
    - General          ← fallback

Logic:
    1. Normalise input (lower-case, strip punctuation)
    2. Count keyword hits per category using weighted rules
    3. Return the category with the highest score (min threshold = 1)
    4. Fall back to "General" if no category crosses the threshold
"""

import re
from typing import Tuple

# ---------------------------------------------------------------------------
# Keyword rule tables
# Each entry: (keyword_pattern, weight)
# ---------------------------------------------------------------------------
_RULES: dict[str, list[tuple[str, int]]] = {
    "Construction": [
        (r"\bconstruct", 3),
        (r"\brenovati", 3),
        (r"\bbuildi?n?g?\b", 2),
        (r"\binfrastructure\b", 2),
        (r"\bcivil\b", 3),
        (r"\barchitect", 2),
        (r"\bcontract", 1),
        (r"\bsite\b", 1),
        (r"\bfoundation\b", 3),
        (r"\bconcrete\b", 3),
        (r"\bstructur", 2),
        (r"\bmep\b", 3),          # Mechanical, Electrical, Plumbing
        (r"\bplumbing\b", 3),
        (r"\belectrical\b", 1),
        (r"\bfacade\b", 3),
        (r"\bfloor(ing)?\b", 2),
        (r"\bapartment\b", 3),
        (r"\boffice tower\b", 3),
        (r"\bbridge\b", 3),
        (r"\broad\b", 2),
        (r"\bhighway\b", 3),
        (r"\bprocurement\b", 1),
        (r"\blandscap", 2),
        (r"\binterior\b", 1),
        (r"\bexterior\b", 1),
        (r"\bresident", 2),
    ],

    "Software / IT": [
        (r"\bsoftware\b", 3),
        (r"\bapplication\b", 2),
        (r"\bapp\b", 2),
        (r"\bmobile\b", 2),
        (r"\bweb\b", 2),
        (r"\bplatform\b", 2),
        (r"\bbackend\b", 3),
        (r"\bfrontend\b", 3),
        (r"\bapi\b", 3),
        (r"\bdatabas", 2),
        (r"\bdevops\b", 3),
        (r"\bci[/ -]?cd\b", 3),
        (r"\bkubernetes\b", 3),
        (r"\bdocker\b", 3),
        (r"\bmicroservice", 3),
        (r"\bcloud\b", 2),
        (r"\baws\b", 3),
        (r"\bazure\b", 3),
        (r"\bgcp\b", 3),
        (r"\bagile\b", 2),
        (r"\bscrum\b", 2),
        (r"\bsprint\b", 2),
        (r"\buser stor", 2),
        (r"\bqa\b", 1),
        (r"\btesting\b", 1),
        (r"\bdeployment\b", 1),
        (r"\bintegration\b", 1),
        (r"\bsystem\b", 1),
        (r"\bdigital transformation\b", 2),
        (r"\bit (project|system|infrastructure)\b", 2),
    ],

    "ERP / SAP": [
        (r"\bsap\b", 4),
        (r"\berp\b", 4),
        (r"\bs/4hana\b", 4),
        (r"\bhana\b", 3),
        (r"\bfiori\b", 3),
        (r"\bsap (mm|sd|fi|co|pp|hr|wm|qm|pm|ps)\b", 4),
        (r"\bsap basis\b", 4),
        (r"\bsap bw\b", 4),
        (r"\bsap crm\b", 4),
        (r"\bsap ariba\b", 4),
        (r"\bsap successfactor", 4),
        (r"\boracle erp\b", 4),
        (r"\boracle financials\b", 4),
        (r"\bdynamics (365|ax|nav|crm)\b", 4),
        (r"\bsalesforce\b", 3),
        (r"\bnetsuite\b", 3),
        (r"\bworkday\b", 3),
        (r"\bimplementati?o?n?\b.*\berp\b", 3),
        (r"\bmigrati?o?n?\b", 2),
        (r"\bgo-?live\b", 3),
        (r"\bcutover\b", 3),
        (r"\bblueprin", 2),
        (r"\bfit.?gap\b", 3),
        (r"\buat\b", 2),
        (r"\bdata migrati", 2),
        (r"\bchange management\b", 1),
        (r"\bconfigur", 1),
        (r"\bcustomiz", 1),
    ],

    "AI / Data": [
        (r"\bartificial intelligence\b", 4),
        (r"\b(ai|ml)\b", 3),
        (r"\bmachine learning\b", 4),
        (r"\bdeep learning\b", 4),
        (r"\bneural net", 4),
        (r"\bllm\b", 4),
        (r"\blarge language model\b", 4),
        (r"\bgpt\b", 3),
        (r"\bdata science\b", 4),
        (r"\bdata engineer", 4),
        (r"\bdata pipeline\b", 4),
        (r"\bdata warehouse\b", 3),
        (r"\bdataset\b", 3),
        (r"\bfeature engineering\b", 4),
        (r"\bmodel train", 4),
        (r"\bmodel deploy", 4),
        (r"\bpredictive\b", 3),
        (r"\banomaly detection\b", 4),
        (r"\bnlp\b", 4),
        (r"\bcomputer vision\b", 4),
        (r"\brecommendation\b", 2),
        (r"\banalytics\b", 2),
        (r"\bbusiness intelligence\b", 2),
        (r"\bdashboard\b", 1),
        (r"\bpython\b", 1),
        (r"\bspark\b", 2),
        (r"\bkafka\b", 2),
        (r"\bethics?\b.*\bai\b", 3),
        (r"\bgenerative\b", 3),
        (r"\brag\b", 3),      # retrieval-augmented generation
        (r"\bfine.?tun", 3),
    ],
}

# Short display labels
_LABELS: dict[str, str] = {
    "Construction":   "Construction",
    "Software / IT":  "Software / IT",
    "ERP / SAP":      "ERP / SAP",
    "AI / Data":      "AI / Data",
    "General":        "General",
}

# Icon / emoji for each type (used in logs / responses)
TYPE_ICONS: dict[str, str] = {
    "Construction":   "🏗️",
    "Software / IT":  "💻",
    "ERP / SAP":      "🔷",
    "AI / Data":      "🤖",
    "General":        "📋",
}


def classify_project(project_name: str, description: str) -> Tuple[str, float]:
    """
    Classify a project into one of the supported types.

    Returns:
        (project_type: str, confidence: float 0–1)
    """
    text = _normalise(f"{project_name} {description}")
    scores: dict[str, float] = {}

    for category, rules in _RULES.items():
        score = 0.0
        for pattern, weight in rules:
            matches = len(re.findall(pattern, text))
            score += matches * weight
        if score > 0:
            scores[category] = score

    if not scores:
        return "General", 0.0

    # Winner
    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    confidence = round(scores[best] / total, 3) if total else 0.0

    return best, confidence


def _normalise(text: str) -> str:
    """Lower-case and collapse whitespace; keep hyphens and slashes."""
    text = text.lower()
    text = re.sub(r"[^\w\s/\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
