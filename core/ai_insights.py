"""
core/ai_insights.py
───────────────────
Enterprise AI Insight Engine for a finished ProjectPlan.

Makes a single Groq call (with one parse-failure retry) and returns structured
JSON suitable for dashboards, KPI cards, tables, and analytics:

  {
    "metrics":             { ... KPI scores / health labels ... },
    "validation":          [ { category, severity, task_id, issue, recommendation } ],
    "risks":               [ { title, severity, probability, impact, affected_phase, mitigation } ],
    "recommendations":     [ { priority, category, title, benefit, implementation_effort } ],
    "executive_summary":   { overall_status, summary }
  }

Independent of the WBS generator and estimator. Does not mutate the plan —
returns a sidecar payload only. Not wired into the planning pipeline yet.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv

from models.schemas import ProjectPlan

try:
    from groq import AsyncGroq
except Exception:  # pragma: no cover — package may be absent in some envs
    AsyncGroq = None  # type: ignore[misc, assignment]

load_dotenv()
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Groq client — same availability pattern as core/wbs_generator.py, but async
# so the public API can await the call without blocking the event loop.
# ---------------------------------------------------------------------------

client: Any = None
if AsyncGroq is not None and os.getenv("GROQ_API_KEY"):
    try:
        client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
    except Exception:
        client = None

_MODEL = "llama-3.3-70b-versatile"
_MAX_TOKENS = 3500
_TEMPERATURE = 0.2

_FALLBACK_MESSAGE = "AI insights are unavailable."

_TOP_LEVEL_KEYS = (
    "metrics",
    "validation",
    "risks",
    "recommendations",
    "executive_summary",
)

_METRIC_KEYS = (
    "complexity_score",
    "risk_score",
    "planning_confidence",
    "estimated_success_rate",
    "budget_health",
    "schedule_health",
    "wbs_completeness",
)

_SCORE_METRIC_KEYS = (
    "complexity_score",
    "risk_score",
    "planning_confidence",
    "estimated_success_rate",
)

_HEALTH_METRIC_KEYS = (
    "budget_health",
    "schedule_health",
    "wbs_completeness",
)

_VALIDATION_KEYS = ("category", "severity", "task_id", "issue", "recommendation")
_RISK_KEYS = (
    "title",
    "severity",
    "probability",
    "impact",
    "affected_phase",
    "mitigation",
)
_RECOMMENDATION_KEYS = (
    "priority",
    "category",
    "title",
    "benefit",
    "implementation_effort",
)
_EXECUTIVE_KEYS = ("overall_status", "summary")

# Domain lenses injected into the prompt by project_type.
_DOMAIN_FOCUS: dict[str, str] = {
    "Construction": (
        "weather delays, permits, contractor coordination, "
        "material availability, and safety"
    ),
    "Software / IT": (
        "testing, QA, deployment, security review, and technical debt"
    ),
    "Software/IT": (
        "testing, QA, deployment, security review, and technical debt"
    ),
    "ERP / SAP": (
        "UAT, integrations, data migration, change management, and user training"
    ),
    "ERP/SAP": (
        "UAT, integrations, data migration, change management, and user training"
    ),
    "AI / Data": (
        "dataset quality, model validation, GPU resources, monitoring, and retraining"
    ),
    "AI/Data": (
        "dataset quality, model validation, GPU resources, monitoring, and retraining"
    ),
    "General": (
        "scope clarity, stakeholder alignment, schedule realism, and budget control"
    ),
}


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def _default_metrics() -> dict[str, Any]:
    """Neutral KPI defaults used when AI insights cannot be generated."""
    return {
        "complexity_score": 0,
        "risk_score": 0,
        "planning_confidence": 0,
        "estimated_success_rate": 0,
        "budget_health": "unknown",
        "schedule_health": "unknown",
        "wbs_completeness": "unknown",
    }


def _fallback_insights(message: str = _FALLBACK_MESSAGE) -> dict[str, Any]:
    """
    Exact enterprise schema returned when Groq is missing or both attempts fail.
    Arrays are empty; metrics use sensible defaults; summary states unavailability.
    """
    return {
        "metrics": _default_metrics(),
        "validation": [],
        "risks": [],
        "recommendations": [],
        "executive_summary": {
            "overall_status": "unavailable",
            "summary": message,
        },
    }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _strip_code_fence(raw: str) -> str:
    """Remove optional markdown fences the model sometimes wraps around JSON."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()
    return text


def _as_str(value: Any, default: str = "") -> str:
    """Coerce a value to a trimmed string; non-scalars become default."""
    if value is None:
        return default
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    return default


def _as_score(value: Any) -> int | None:
    """
    Coerce a metric score to an int in [0, 100].
    Returns None if the value cannot be interpreted as a number.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        score = int(round(float(value)))
    elif isinstance(value, str):
        text = value.strip().rstrip("%")
        try:
            score = int(round(float(text)))
        except ValueError:
            return None
    else:
        return None

    return max(0, min(100, score))


def _require_keys(obj: Any, keys: tuple[str, ...]) -> dict[str, Any] | None:
    """Return obj if it is a dict containing every required key; else None."""
    if not isinstance(obj, dict):
        return None
    if not all(key in obj for key in keys):
        return None
    return obj


def _normalise_metrics(raw: Any) -> dict[str, Any] | None:
    """Validate and normalise the metrics object."""
    metrics = _require_keys(raw, _METRIC_KEYS)
    if metrics is None:
        return None

    normalised: dict[str, Any] = {}
    for key in _SCORE_METRIC_KEYS:
        score = _as_score(metrics[key])
        if score is None:
            return None
        normalised[key] = score

    for key in _HEALTH_METRIC_KEYS:
        label = _as_str(metrics[key])
        if not label:
            return None
        normalised[key] = label

    return normalised


def _normalise_validation_item(item: Any) -> dict[str, str] | None:
    row = _require_keys(item, _VALIDATION_KEYS)
    if row is None:
        return None
    return {key: _as_str(row[key]) for key in _VALIDATION_KEYS}


def _normalise_risk_item(item: Any) -> dict[str, str] | None:
    row = _require_keys(item, _RISK_KEYS)
    if row is None:
        return None
    return {key: _as_str(row[key]) for key in _RISK_KEYS}


def _normalise_recommendation_item(item: Any) -> dict[str, str] | None:
    row = _require_keys(item, _RECOMMENDATION_KEYS)
    if row is None:
        return None
    return {key: _as_str(row[key]) for key in _RECOMMENDATION_KEYS}


def _normalise_object_list(
    raw: Any,
    normaliser: Any,
) -> list[dict[str, str]] | None:
    """Normalise a list of structured objects; reject if any item is invalid."""
    if not isinstance(raw, list):
        return None

    items: list[dict[str, str]] = []
    for entry in raw:
        normalised = normaliser(entry)
        if normalised is None:
            return None
        items.append(normalised)
    return items


def _normalise_executive_summary(raw: Any) -> dict[str, str] | None:
    summary = _require_keys(raw, _EXECUTIVE_KEYS)
    if summary is None:
        return None

    overall_status = _as_str(summary["overall_status"])
    text = _as_str(summary["summary"])
    if not overall_status or not text:
        return None

    return {
        "overall_status": overall_status,
        "summary": text,
    }


def _normalise_insights(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Validate the full enterprise schema and coerce field types.
    Returns None if any required section or nested field is unusable.
    """
    if not isinstance(payload, dict):
        return None
    if not all(key in payload for key in _TOP_LEVEL_KEYS):
        return None

    metrics = _normalise_metrics(payload["metrics"])
    if metrics is None:
        return None

    validation = _normalise_object_list(
        payload["validation"], _normalise_validation_item
    )
    if validation is None:
        return None

    risks = _normalise_object_list(payload["risks"], _normalise_risk_item)
    if risks is None:
        return None

    recommendations = _normalise_object_list(
        payload["recommendations"], _normalise_recommendation_item
    )
    if recommendations is None:
        return None

    executive_summary = _normalise_executive_summary(payload["executive_summary"])
    if executive_summary is None:
        return None

    return {
        "metrics": metrics,
        "validation": validation,
        "risks": risks,
        "recommendations": recommendations,
        "executive_summary": executive_summary,
    }


def _parse_insights_json(raw: str) -> dict[str, Any] | None:
    """Parse model output into a normalised insights dict, or None on failure."""
    try:
        cleaned = _strip_code_fence(raw)
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("AI insights JSON parse failed: %s", exc)
        return None

    return _normalise_insights(data)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _domain_focus(project_type: str) -> str:
    """Resolve domain-specific analysis lens for the given project type."""
    if project_type in _DOMAIN_FOCUS:
        return _DOMAIN_FOCUS[project_type]

    # Soft match on common aliases / punctuation differences.
    normalised = project_type.strip().lower().replace("–", "/")
    for key, focus in _DOMAIN_FOCUS.items():
        if key.lower() == normalised or key.lower().replace(" ", "") == normalised.replace(" ", ""):
            return focus
    return _DOMAIN_FOCUS["General"]


def _plan_snapshot(plan: ProjectPlan) -> str:
    """Compact, LLM-friendly serialisation of the finished plan."""
    tasks_lines: list[str] = []
    for task in plan.tasks:
        deps = ", ".join(task.dependencies) if task.dependencies else "none"
        tasks_lines.append(
            f'  - id={task.id} | L{task.level} | "{task.name}" | '
            f"days={task.duration_days} | cost=${task.estimated_cost:,.2f} | "
            f"parent={task.parent_id or 'root'} | deps=[{deps}] | "
            f"start={task.start_date or 'n/a'} | end={task.end_date or 'n/a'}"
        )

    body = "\n".join(tasks_lines) if tasks_lines else "  (no tasks)"
    return (
        f"project_id: {plan.project_id}\n"
        f"project_name: {plan.project_name}\n"
        f"project_type: {plan.project_type}\n"
        f"total_budget: USD {plan.total_budget:,.2f}\n"
        f"start_date: {plan.start_date or 'n/a'}\n"
        f"end_date: {plan.end_date or 'n/a'}\n"
        f"task_count: {len(plan.tasks)}\n"
        f"tasks:\n{body}"
    )


def _build_prompt(
    plan: ProjectPlan,
    project_name: str,
    description: str,
    project_type: str,
) -> str:
    """
    Single-shot enterprise prompt: one Groq call returns the full insight schema.
    Instructs evidence-only analysis and domain-aware risk lenses.
    """
    domain_lens = _domain_focus(project_type)

    return f"""You are a senior SAP Project Systems consultant, PMP-certified project manager, enterprise project planner, and risk analyst.

PROJECT CONTEXT:
  Name: {project_name}
  Type: {project_type}
  Description: {description}

FINISHED PLAN:
{_plan_snapshot(plan)}

DOMAIN LENS ({project_type}):
  Emphasise {domain_lens}.

ANALYSIS OBJECTIVES:
Evaluate the finished plan against evidence in the plan data only. Cover:
  - WBS completeness
  - Budget distribution
  - Schedule feasibility
  - Dependency correctness
  - Missing phases
  - Timeline realism
  - Resource bottlenecks
  - Cost allocation
  - Project risks
  - Overall project quality

EVIDENCE RULES:
  - Never invent facts, tasks, dates, costs, or dependencies that are not present.
  - If evidence is insufficient, say so explicitly in the relevant fields.
  - Prefer [] for validation/risks/recommendations when nothing material can be supported.
  - task_id and affected_phase must reference real IDs/names from the plan, or "" if unknown.

RETURN ONLY a valid JSON object with exactly these keys and shapes:

{{
  "metrics": {{
    "complexity_score": 0,
    "risk_score": 0,
    "planning_confidence": 0,
    "estimated_success_rate": 0,
    "budget_health": "",
    "schedule_health": "",
    "wbs_completeness": ""
  }},
  "validation": [
    {{
      "category": "",
      "severity": "",
      "task_id": "",
      "issue": "",
      "recommendation": ""
    }}
  ],
  "risks": [
    {{
      "title": "",
      "severity": "",
      "probability": "",
      "impact": "",
      "affected_phase": "",
      "mitigation": ""
    }}
  ],
  "recommendations": [
    {{
      "priority": "",
      "category": "",
      "title": "",
      "benefit": "",
      "implementation_effort": ""
    }}
  ],
  "executive_summary": {{
    "overall_status": "",
    "summary": ""
  }}
}}

FIELD GUIDANCE:
  - Score metrics must be integers from 0 to 100.
  - Health labels should be short (e.g. "healthy", "watch", "at_risk", "critical", "unknown").
  - severity / priority / probability / impact: use concise enums such as low|medium|high|critical.
  - Prefer 3–8 items per list when evidence supports them.
  - executive_summary.overall_status: short status label (e.g. "on_track", "watch", "at_risk", "critical").
  - executive_summary.summary: 2–4 sentence leadership briefing grounded in the plan.

OUTPUT RULES:
  - Return ONLY valid JSON.
  - No markdown.
  - No explanations.
  - No code fences.
"""


# ---------------------------------------------------------------------------
# Groq call + retry
# ---------------------------------------------------------------------------

async def _call_groq(prompt: str) -> str | None:
    """Execute one chat completion. Returns raw content or None on failure."""
    if client is None:
        return None

    try:
        response = await client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
        )
        content = response.choices[0].message.content
        if not content or not str(content).strip():
            log.warning("AI insights returned empty content")
            return None
        return str(content).strip()
    except Exception as exc:
        log.warning("AI insights Groq call failed: %s", exc)
        return None


async def _generate_with_retry(prompt: str) -> dict[str, Any] | None:
    """
    Attempt generation with exactly one retry if JSON parsing / normalisation fails.

    Note: each attempt is one Groq request. A successful first parse uses a
    single call; a parse failure triggers one additional call only.
    """
    raw = await _call_groq(prompt)
    if raw is None:
        return None

    parsed = _parse_insights_json(raw)
    if parsed is not None:
        return parsed

    log.info("AI insights parse failed; retrying once")
    raw_retry = await _call_groq(prompt)
    if raw_retry is None:
        return None

    return _parse_insights_json(raw_retry)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_ai_insights(
    project_plan: ProjectPlan,
    project_name: str,
    description: str,
    project_type: str,
) -> dict[str, Any]:
    """
    Analyse a finished project plan and return enterprise AI insights.

    Return shape:
      {
        "metrics": {
          "complexity_score": int,
          "risk_score": int,
          "planning_confidence": int,
          "estimated_success_rate": int,
          "budget_health": str,
          "schedule_health": str,
          "wbs_completeness": str
        },
        "validation": [ { category, severity, task_id, issue, recommendation } ],
        "risks": [ { title, severity, probability, impact, affected_phase, mitigation } ],
        "recommendations": [ { priority, category, title, benefit, implementation_effort } ],
        "executive_summary": { overall_status, summary }
      }

    If Groq is unavailable or both attempts fail, returns the same schema with
    default metrics, empty arrays, and an unavailable executive summary.
    Never raises for AI / network failures.
    """
    if client is None:
        log.info("AI insights client unavailable; returning fallback")
        return _fallback_insights(_FALLBACK_MESSAGE)

    prompt = _build_prompt(project_plan, project_name, description, project_type)
    insights = await _generate_with_retry(prompt)

    if insights is None:
        log.warning("AI insights generation failed after retry; returning fallback")
        return _fallback_insights(_FALLBACK_MESSAGE)

    return insights
