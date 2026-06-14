"""
core/wbs_generator.py
─────────────────────
Hybrid WBS generation pipeline:

  Step 1  Rule-based template  →  guaranteed phase skeleton (IDs, names, budgets, durations)
  Step 2  AI expansion         →  project-specific deliverable names for each sub-task
  Step 3  Assembly             →  merge skeleton + AI names into final WBSTask objects
  Step 4  Fallback             →  template task names if AI is unavailable or fails

The LLM is only asked to produce *task names* — no IDs, no budgets, no structure.
Budget and schedule come entirely from the template, making the output deterministic
and easy to validate.
"""

import os
import json
import logging
from dotenv import load_dotenv
from models.schemas import WBSTask, ProjectPlan

try:
    from groq import Groq
except Exception:
    Groq = None

load_dotenv()
log = logging.getLogger(__name__)

client = None
if Groq is not None and os.getenv("GROQ_API_KEY"):
    try:
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    except Exception:
        client = None


# ─────────────────────────────────────────────────────────────────────────────
# Domain-specific WBS templates
#
# Each entry:  (phase_name, budget_weight, duration_days, [children])
# Child entry: (fallback_task_name, budget_weight, duration_days)
#
# Budget weights across all L1 phases sum to 1.0.
# Child budget_weight is a fraction of total_budget (not of the phase).
# ─────────────────────────────────────────────────────────────────────────────

_TEMPLATES: dict[str, list] = {

    # ── CONSTRUCTION ──────────────────────────────────────────────────────────
    "Construction": [
        ("Site Preparation", 0.08, 14, [
            ("Land Survey & Geotechnical Assessment", 0.02, 5),
            ("Site Clearing & Grading",               0.03, 7),
            ("Temporary Facilities & Safety Setup",   0.03, 5),
        ]),
        ("Foundation Work", 0.15, 25, [
            ("Excavation & Earthworks",               0.05, 10),
            ("Pile / Footing Installation",           0.06, 10),
            ("Foundation Slab & Waterproofing",       0.04,  8),
        ]),
        ("Structural Construction", 0.28, 55, [
            ("Reinforced Concrete Frame & Columns",   0.10, 22),
            ("Floor Slabs & Staircases",              0.10, 18),
            ("Roof Structure & Waterproofing",        0.08, 15),
        ]),
        ("Electrical & Plumbing", 0.18, 35, [
            ("Electrical Wiring & Distribution Boards", 0.07, 14),
            ("Plumbing & Drainage Systems",           0.06, 13),
            ("HVAC & Fire Suppression Systems",       0.05, 12),
        ]),
        ("Interior Finishing", 0.20, 40, [
            ("Masonry, Plastering & Tiling",          0.08, 18),
            ("Doors, Windows & Glazing",              0.06, 12),
            ("Painting, Fixtures & Fittings",         0.06, 12),
        ]),
        ("Inspection & Handover", 0.11, 16, [
            ("Structural & MEP Inspection",           0.04,  6),
            ("Snag List Resolution",                  0.04,  6),
            ("Commissioning & Final Handover",        0.03,  5),
        ]),
    ],

    # ── SOFTWARE / IT ─────────────────────────────────────────────────────────
    "Software / IT": [
        ("Requirement Analysis", 0.10, 12, [
            ("Functional & Non-Functional Specification", 0.04, 5),
            ("System Architecture Decision Records",      0.03, 4),
            ("Backlog & Story Mapping",                   0.03, 4),
        ]),
        ("UI/UX Design", 0.12, 14, [
            ("User Journey Maps & Wireframes",        0.04,  5),
            ("High-Fidelity Prototypes",              0.05,  6),
            ("Design System & Component Library",     0.03,  5),
        ]),
        ("Backend Development", 0.22, 35, [
            ("Database Schema & Migrations",          0.06, 12),
            ("REST / GraphQL API Development",        0.10, 16),
            ("Auth, Security & Middleware Layer",     0.06, 10),
        ]),
        ("Frontend Development", 0.20, 30, [
            ("UI Screen Implementation",              0.08, 14),
            ("API Integration & State Management",    0.07, 10),
            ("Responsive Layout & Accessibility",     0.05,  8),
        ]),
        ("Testing & QA", 0.18, 20, [
            ("Unit & Integration Test Suites",        0.06,  8),
            ("E2E, Regression & Performance Tests",   0.07,  8),
            ("Security & Penetration Testing",        0.05,  6),
        ]),
        ("Deployment", 0.18, 15, [
            ("CI/CD Pipeline & Infrastructure-as-Code", 0.06, 6),
            ("Staging Validation & User Acceptance",  0.07,  6),
            ("Production Go-Live & Monitoring Setup", 0.05,  5),
        ]),
    ],

    # ── ERP / SAP ─────────────────────────────────────────────────────────────
    "ERP / SAP": [
        ("Business Blueprint", 0.14, 28, [
            ("As-Is Process Documentation",           0.05, 10),
            ("To-Be Process Design & Fit-Gap",        0.06, 12),
            ("Blueprint Sign-off & Scope Baseline",   0.03,  7),
        ]),
        ("System Configuration", 0.24, 40, [
            ("Core Module Configuration (FI/CO/MM/SD)", 0.10, 18),
            ("Custom ABAP Developments & BADIs",      0.09, 16),
            ("Workflow & Output Form Configuration",  0.05,  8),
        ]),
        ("Data Migration", 0.16, 25, [
            ("Data Extraction & Cleansing",           0.06, 10),
            ("Data Mapping & Transformation Rules",   0.05,  8),
            ("Mock Load, Validation & Sign-off",      0.05,  8),
        ]),
        ("Integration", 0.14, 20, [
            ("Interface Functional & Technical Spec", 0.05,  8),
            ("Middleware / iDoc / API Build",         0.06,  8),
            ("Integration & Error-Handling Tests",    0.03,  5),
        ]),
        ("Testing", 0.16, 22, [
            ("Unit & String Testing",                 0.06,  9),
            ("User Acceptance Testing (UAT)",         0.07,  9),
            ("Regression & Performance Benchmarks",   0.03,  5),
        ]),
        ("Go-Live & Support", 0.16, 20, [
            ("Cutover Planning & Dress Rehearsal",    0.05,  8),
            ("Production Go-Live Execution",          0.06,  7),
            ("Hyper-care & Issue Resolution",         0.05,  8),
        ]),
    ],

    # ── AI / DATA ─────────────────────────────────────────────────────────────
    "AI / Data": [
        ("Data Collection", 0.12, 18, [
            ("Source Identification & Access Agreements", 0.04, 7),
            ("Data Ingestion Pipeline Build",             0.05, 8),
            ("Raw Data Storage & Cataloguing",            0.03, 5),
        ]),
        ("Data Preprocessing", 0.16, 20, [
            ("Exploratory Data Analysis (EDA)",       0.05,  8),
            ("Data Cleaning & Outlier Handling",      0.06,  8),
            ("Feature Engineering & Transformation",  0.05,  7),
        ]),
        ("Model Development", 0.20, 25, [
            ("Baseline Model Selection & Benchmarking", 0.06, 9),
            ("Feature Selection & Dataset Splits",      0.06, 8),
            ("Model Architecture Design",               0.08, 9),
        ]),
        ("Model Training", 0.22, 28, [
            ("Training Pipeline & Experiment Tracking", 0.07, 10),
            ("Hyperparameter Optimisation",              0.08, 12),
            ("Cross-Validation & Bias Assessment",       0.07,  9),
        ]),
        ("Evaluation", 0.14, 16, [
            ("Performance Metrics & Benchmark Report", 0.05, 6),
            ("A/B Testing & Business Validation",       0.05, 6),
            ("Fairness, Robustness & Explainability",   0.04, 5),
        ]),
        ("Deployment", 0.16, 18, [
            ("Model Packaging & Serving API",          0.06, 7),
            ("MLOps Pipeline & Drift Monitoring",      0.06, 7),
            ("Documentation & Knowledge Transfer",     0.04, 5),
        ]),
    ],

    # ── GENERAL (fallback) ────────────────────────────────────────────────────
    "General": [
        ("Initiation & Planning", 0.10, 12, [
            ("Stakeholder Analysis & Project Charter", 0.04, 5),
            ("Requirements & Scope Definition",        0.04, 5),
            ("Risk & Resource Planning",               0.02, 4),
        ]),
        ("Design & Preparation", 0.15, 15, [
            ("Solution Architecture Design",           0.08, 8),
            ("Detailed Design & Prototyping",          0.07, 8),
        ]),
        ("Execution — Phase 1", 0.25, 30, [
            ("Core Deliverable Development A",         0.12, 15),
            ("Core Deliverable Development B",         0.13, 16),
        ]),
        ("Execution — Phase 2", 0.25, 25, [
            ("Integration & System Testing",           0.13, 13),
            ("Quality Review & Rework",                0.12, 13),
        ]),
        ("Deployment & Closure", 0.15, 12, [
            ("Go-Live / Final Delivery",               0.09, 7),
            ("Stakeholder Acceptance Sign-off",        0.06, 5),
        ]),
        ("Post-Delivery Review", 0.10, 8, [
            ("Lessons Learned Workshop",               0.04, 4),
            ("Documentation & Handover Package",       0.06, 5),
        ]),
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Build template skeleton
# Returns a list of phase dicts, each containing their child slot metadata.
# ─────────────────────────────────────────────────────────────────────────────

def _build_skeleton(
    project_id:   str,
    project_type: str,
    total_budget: float,
) -> list[dict]:
    """
    Returns a skeleton list.  Each item is a dict with:
      phase:    the L1 task dict (ready to append to final tasks)
      children: list of child slot dicts, each containing
                  id, parent_id, level, duration_days, estimated_cost,
                  fallback_name   (used if AI can't provide a better name)
    """
    phases = _TEMPLATES.get(project_type, _TEMPLATES["General"])
    skeleton = []

    for phase_idx, (phase_name, phase_wt, phase_days, children) in enumerate(phases):
        phase_num  = phase_idx + 1
        phase_id   = f"{project_id}-{phase_num:02d}"
        phase_cost = round(total_budget * phase_wt, 2)
        prev_phase = f"{project_id}-{phase_num - 1:02d}" if phase_num > 1 else None

        phase_task = {
            "id":             phase_id,
            "name":           phase_name,       # phase name is FIXED — not touched by AI
            "level":          1,
            "parent_id":      None,
            "duration_days":  phase_days,
            "estimated_cost": phase_cost,
            "dependencies":   [prev_phase] if prev_phase else [],
            "start_date":     None,
            "end_date":       None,
        }

        child_slots = []
        prev_child: str | None = None
        for child_idx, (fallback_name, child_wt, child_days) in enumerate(children):
            child_num  = child_idx + 1
            child_id   = f"{phase_id}-{child_num:02d}"
            child_cost = round(total_budget * child_wt, 2)

            child_slots.append({
                "id":            child_id,
                "parent_id":     phase_id,
                "level":         2,
                "duration_days": child_days,
                "estimated_cost": child_cost,
                "dependencies":  [prev_child] if prev_child else [],
                "start_date":    None,
                "end_date":      None,
                "fallback_name": fallback_name,
            })
            prev_child = child_id

        skeleton.append({"phase": phase_task, "children": child_slots})

    return skeleton


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — AI expansion
# Ask the LLM to produce deliverable-based task names for every child slot.
# The LLM only needs to return names — all structure lives in the skeleton.
# ─────────────────────────────────────────────────────────────────────────────

_DOMAIN_CONTEXT: dict[str, str] = {
    "Construction":  "civil construction deliverables, contractor work packages, and SAP PS network activities",
    "Software / IT": "software engineering deliverables, sprint epics, and system components",
    "ERP / SAP":     "SAP PS work packages, RICEF objects, and project management deliverables",
    "AI / Data":     "data engineering deliverables, ML experiment artefacts, and MLOps work packages",
    "General":       "project management deliverables and milestone-based work packages",
}


def _ai_expand(
    project_name:  str,
    description:   str,
    project_type:  str,
    total_budget:  float,
    skeleton:      list[dict],
) -> dict[str, list[str]] | None:
    """
    Calls the LLM to rename each child slot with a project-specific,
    deliverable-based task name.

    Returns a dict mapping phase_id → [task_name_for_slot_1, task_name_for_slot_2, …]
    or None if the call fails or produces unusable output.
    """
    if client is None:
        return None

    domain_ctx = _DOMAIN_CONTEXT.get(project_type, _DOMAIN_CONTEXT["General"])

    # Build a compact slot table to send to the LLM
    slot_lines = []
    for entry in skeleton:
        phase = entry["phase"]
        for child in entry["children"]:
            slot_lines.append(
                f'  "{child["id"]}": parent="{phase["name"]}", '
                f'budget=${child["estimated_cost"]:,.0f}, '
                f'duration={child["duration_days"]}d'
            )
    slot_table = "\n".join(slot_lines)

    prompt = f"""You are an expert project planner generating a Work Breakdown Structure for a real {project_type} project.

PROJECT:
  Name:    {project_name}
  Budget:  USD {total_budget:,.0f}
  Scope:   {description}

TASK:
For each slot below, write ONE concise, deliverable-based task name (4–10 words).
Rules:
  - Names must reflect THIS specific project — not generic placeholders.
  - Use {domain_ctx} terminology.
  - Avoid vague words like "Initiation", "Planning", "Stakeholder Interviews", "Review".
  - Each name must be a concrete deliverable or work-package output.
  - Keep the same slot order.

SLOTS:
{slot_table}

Return ONLY a valid JSON object mapping each slot ID to its task name.
No markdown. No explanation. Example:
{{
  "PRJ-01-01": "Soil Boring Report & Geotechnical Certification",
  "PRJ-01-02": "Temporary Site Hoarding & Access Road Construction"
}}"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        ai_names: dict[str, str] = json.loads(raw)

        # Re-key by phase_id → [ordered child names]
        result: dict[str, list[str]] = {}
        for entry in skeleton:
            phase_id = entry["phase"]["id"]
            names = []
            for child in entry["children"]:
                name = ai_names.get(child["id"], "").strip()
                if name:
                    names.append(name)
            if names:
                result[phase_id] = names

        # Only accept if we got names for every phase
        if len(result) == len(skeleton):
            return result
        return None

    except Exception as exc:
        log.warning("AI expansion failed: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Assemble final task list
# Merge the skeleton with AI-provided names (or fallback to template names).
# ─────────────────────────────────────────────────────────────────────────────

def _assemble(
    skeleton:  list[dict],
    ai_names:  dict[str, list[str]] | None,
) -> list[dict]:
    """
    Produces the final flat list of task dicts, ready for WBSTask(**t).
    Phase names come from the template (fixed).
    Child names come from AI if available, else from the template fallback.
    """
    tasks: list[dict] = []

    for entry in skeleton:
        phase = entry["phase"]
        tasks.append({k: v for k, v in phase.items()})  # copy, strip skeleton-only keys

        phase_id    = phase["id"]
        phase_names = ai_names.get(phase_id, []) if ai_names else []

        for idx, child in enumerate(entry["children"]):
            # Pick AI name if available and non-empty
            if idx < len(phase_names) and phase_names[idx]:
                task_name = phase_names[idx]
            else:
                task_name = child["fallback_name"]

            tasks.append({
                "id":             child["id"],
                "name":           task_name,
                "level":          child["level"],
                "parent_id":      child["parent_id"],
                "duration_days":  child["duration_days"],
                "estimated_cost": child["estimated_cost"],
                "dependencies":   child["dependencies"],
                "start_date":     child["start_date"],
                "end_date":       child["end_date"],
            })

    return tasks


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_wbs(
    project_name: str,
    description:  str,
    project_type: str,
    total_budget: float,
    project_id:   str,
) -> ProjectPlan:
    """
    Hybrid WBS generation:
      1. Build a domain-specific template skeleton (guaranteed structure).
      2. AI expands each phase's child slots into project-specific deliverable names.
      3. Assemble final task list, falling back to template names per slot if AI fails.
    """

    # Step 1 — skeleton
    skeleton = _build_skeleton(project_id, project_type, total_budget)

    # Step 2 — AI expansion (best-effort)
    ai_names = _ai_expand(project_name, description, project_type, total_budget, skeleton)

    # Step 3 — assemble
    tasks_data = _assemble(skeleton, ai_names)

    tasks = [WBSTask(**t) for t in tasks_data]

    return ProjectPlan(
        project_id=project_id,
        project_name=project_name,
        project_type=project_type,
        total_budget=total_budget,
        tasks=tasks,
    )