from pydantic import BaseModel
from typing import Optional, List


class WBSTask(BaseModel):
    id: str
    name: str
    level: int
    parent_id: Optional[str]
    duration_days: int
    estimated_cost: float
    dependencies: List[str] = []
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ProjectPlan(BaseModel):
    project_id: str
    project_name: str
    project_type: str
    total_budget: float
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    tasks: List[WBSTask]


# ✅ UPDATED REQUEST MODEL
class ProjectRequest(BaseModel):
    project_name: str
    description: str
    total_budget: float
    start_date: str
    series_prefix: Optional[str] = None  