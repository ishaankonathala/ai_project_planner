"""Unit tests for budget allocation, timeline calculation, and pipeline integration."""

import unittest
from datetime import datetime, timedelta

from core.estimator import allocate_budget, apply_estimations, calculate_timeline
from core.wbs_generator import generate_wbs
from models.schemas import ProjectPlan, WBSTask


def _sample_tasks() -> list[WBSTask]:
    """Two-phase WBS mirroring the generator's L1/L2 structure."""
    return [
        WBSTask(
            id="PRJ-01",
            name="Phase One",
            level=1,
            parent_id=None,
            duration_days=10,
            estimated_cost=40000.0,
            dependencies=[],
        ),
        WBSTask(
            id="PRJ-01-01",
            name="Task A",
            level=2,
            parent_id="PRJ-01",
            duration_days=5,
            estimated_cost=25000.0,
            dependencies=[],
        ),
        WBSTask(
            id="PRJ-01-02",
            name="Task B",
            level=2,
            parent_id="PRJ-01",
            duration_days=5,
            estimated_cost=25000.0,
            dependencies=["PRJ-01-01"],
        ),
        WBSTask(
            id="PRJ-02",
            name="Phase Two",
            level=1,
            parent_id=None,
            duration_days=8,
            estimated_cost=60000.0,
            dependencies=["PRJ-01"],
        ),
        WBSTask(
            id="PRJ-02-01",
            name="Task C",
            level=2,
            parent_id="PRJ-02",
            duration_days=4,
            estimated_cost=30000.0,
            dependencies=[],
        ),
        WBSTask(
            id="PRJ-02-02",
            name="Task D",
            level=2,
            parent_id="PRJ-02",
            duration_days=4,
            estimated_cost=30000.0,
            dependencies=["PRJ-02-01"],
        ),
    ]


class AllocateBudgetTests(unittest.TestCase):
    def test_leaf_costs_sum_to_total_budget(self):
        tasks = _sample_tasks()
        total_budget = 100_000.0

        result = allocate_budget(tasks, total_budget)
        leaves = [t for t in result if t.level == 2]

        self.assertEqual(sum(t.estimated_cost for t in leaves), total_budget)

    def test_parent_costs_roll_up_from_children(self):
        tasks = _sample_tasks()
        total_budget = 100_000.0

        result = allocate_budget(tasks, total_budget)

        for phase in [t for t in result if t.level == 1]:
            children = [t for t in result if t.parent_id == phase.id]
            self.assertEqual(phase.estimated_cost, sum(c.estimated_cost for c in children))


class CalculateTimelineTests(unittest.TestCase):
    def test_every_task_gets_start_and_end_dates(self):
        tasks = _sample_tasks()
        project_start = "2026-01-15"

        result = calculate_timeline(tasks, project_start)

        for task in result:
            self.assertIsNotNone(task.start_date)
            self.assertIsNotNone(task.end_date)
            self.assertRegex(task.start_date, r"^\d{4}-\d{2}-\d{2}$")
            self.assertRegex(task.end_date, r"^\d{4}-\d{2}-\d{2}$")

    def test_dependency_ordering(self):
        tasks = _sample_tasks()
        project_start = "2026-01-15"

        result = calculate_timeline(tasks, project_start)
        by_id = {t.id: t for t in result}

        # Sibling chain: B starts the day after A ends
        task_a = by_id["PRJ-01-01"]
        task_b = by_id["PRJ-01-02"]
        expected_b_start = (
            datetime.strptime(task_a.end_date, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        self.assertEqual(task_b.start_date, expected_b_start)

        # Phase two starts the day after phase one ends
        phase_one = by_id["PRJ-01"]
        phase_two = by_id["PRJ-02"]
        expected_phase_two_start = (
            datetime.strptime(phase_one.end_date, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        self.assertEqual(phase_two.start_date, expected_phase_two_start)

    def test_duration_matches_inclusive_end_date(self):
        tasks = [
            WBSTask(
                id="PRJ-01-01",
                name="Single",
                level=2,
                parent_id="PRJ-01",
                duration_days=5,
                estimated_cost=1000.0,
                dependencies=[],
            )
        ]
        result = calculate_timeline(tasks, "2026-03-01")
        task = result[0]

        start = datetime.strptime(task.start_date, "%Y-%m-%d")
        end = datetime.strptime(task.end_date, "%Y-%m-%d")
        self.assertEqual((end - start).days + 1, 5)


class ApplyEstimationsTests(unittest.TestCase):
    def test_plan_returns_project_start_and_end_dates(self):
        plan = ProjectPlan(
            project_id="PRJ-TEST",
            project_name="Test Project",
            project_type="General",
            total_budget=100_000.0,
            tasks=_sample_tasks(),
        )

        result = apply_estimations(plan, "2026-06-01")

        self.assertIsNotNone(result.start_date)
        self.assertIsNotNone(result.end_date)
        self.assertLessEqual(result.start_date, result.end_date)

        task_starts = [t.start_date for t in result.tasks if t.start_date]
        task_ends = [t.end_date for t in result.tasks if t.end_date]
        self.assertEqual(result.start_date, min(task_starts))
        self.assertEqual(result.end_date, max(task_ends))


class PipelineIntegrationTests(unittest.TestCase):
    def test_generate_wbs_plus_apply_estimations(self):
        plan = generate_wbs(
            project_name="Office Tower",
            description="Commercial building construction project",
            project_type="Construction",
            total_budget=500_000.0,
            project_id="PRJ-PIPE-01",
        )
        result = apply_estimations(plan, "2026-04-01")

        leaves = [t for t in result.tasks if t.level == 2]
        self.assertGreater(len(leaves), 0)
        self.assertEqual(sum(t.estimated_cost for t in leaves), result.total_budget)

        for task in result.tasks:
            self.assertIsNotNone(task.start_date)
            self.assertIsNotNone(task.end_date)

        self.assertIsNotNone(result.start_date)
        self.assertIsNotNone(result.end_date)


if __name__ == "__main__":
    unittest.main()
