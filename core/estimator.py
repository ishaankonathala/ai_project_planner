import networkx as nx
from datetime import datetime, timedelta
from models.schemas import WBSTask, ProjectPlan
from typing import List

def calculate_timeline(tasks: List[WBSTask], project_start: str = None) -> List[WBSTask]:
    if not project_start:
        project_start = datetime.today().strftime("%Y-%m-%d")

    start_dt = datetime.strptime(project_start, "%Y-%m-%d")

    G = nx.DiGraph()
    task_map = {t.id: t for t in tasks}

    for task in tasks:
        G.add_node(task.id)

    for task in tasks:
        for dep in task.dependencies:
            if dep in task_map:
                G.add_edge(dep, task.id)

    start_dates = {}
    end_dates = {}

    for task_id in nx.topological_sort(G):
        task = task_map[task_id]
        if not task.dependencies:
            start_dates[task_id] = start_dt
        else:
            latest_end = max(
                end_dates[dep] for dep in task.dependencies if dep in end_dates
            )
            start_dates[task_id] = latest_end + timedelta(days=1)

        end_dates[task_id] = start_dates[task_id] + timedelta(days=task.duration_days - 1)

    updated_tasks = []
    for task in tasks:
        task.start_date = start_dates[task.id].strftime("%Y-%m-%d")
        task.end_date = end_dates[task.id].strftime("%Y-%m-%d")
        updated_tasks.append(task)

    return updated_tasks


def allocate_budget(tasks: List[WBSTask], total_budget: float) -> List[WBSTask]:
  """Scale leaf-level costs to *total_budget* and roll up parent costs from children."""
  if not tasks:
    return tasks

  leaf_level = max(t.level for t in tasks)
  leaf_tasks = [t for t in tasks if t.level == leaf_level]
  total_estimated = sum(t.estimated_cost for t in leaf_tasks)

  if total_estimated > 0:
    scaled_costs = [
      round((t.estimated_cost / total_estimated) * total_budget, 2)
      for t in leaf_tasks
    ]
    remainder = round(total_budget - sum(scaled_costs), 2)
    if scaled_costs:
      scaled_costs[-1] = round(scaled_costs[-1] + remainder, 2)
    for task, cost in zip(leaf_tasks, scaled_costs):
      task.estimated_cost = cost

  for level in range(leaf_level - 1, 0, -1):
    for task in tasks:
      if task.level != level:
        continue
      children = [t for t in tasks if t.parent_id == task.id]
      if children:
        task.estimated_cost = round(sum(c.estimated_cost for c in children), 2)

  return tasks


def apply_estimations(plan: ProjectPlan, project_start: str = None) -> ProjectPlan:
    plan.tasks = allocate_budget(plan.tasks, plan.total_budget)
    plan.tasks = calculate_timeline(plan.tasks, project_start)

    all_start_dates = [t.start_date for t in plan.tasks if t.start_date]
    all_end_dates = [t.end_date for t in plan.tasks if t.end_date]

    if all_start_dates:
        plan.start_date = min(all_start_dates)
    if all_end_dates:
        plan.end_date = max(all_end_dates)

    return plan
