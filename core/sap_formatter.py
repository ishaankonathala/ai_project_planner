from models.schemas import ProjectPlan, WBSTask
from typing import Dict, Any
from datetime import datetime


def format_sap_date(date_str: str) -> str:
    if not date_str:
        return ""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"/Date({int(dt.timestamp() * 1000)})/"


def format_sap_project(plan: ProjectPlan) -> Dict[str, Any]:
    project_code = "10001"

    wbs_elements = []

    for task in plan.tasks:
        wbs_elements.append({
            "POSID": task.id,
            "POST1": task.name,
            "STUFE": str(task.level),
            "BUDGET": str(task.estimated_cost),
            "PLFAZ": format_sap_date(task.start_date),
            "PLSEZ": format_sap_date(task.end_date),
            "DAUER": str(task.duration_days)
        })

    return {
        "d": {
            "results": {
                "ProjectSet": {
                    "PSPNR": project_code,
                    "POST1": plan.project_name,
                    "PLFAZ": format_sap_date(plan.start_date),
                    "PLSEZ": format_sap_date(plan.end_date),
                    "BUDGET": str(plan.total_budget)
                },
                "WBSElementSet": wbs_elements
            }
        }
    }