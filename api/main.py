from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models.schemas import ProjectRequest
from core.id_generator import generate_project_id
from core.classifier import classify_project
from core.wbs_generator import generate_wbs

app = FastAPI(title="AXIOM API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/generate-plan")
def generate_plan(request: ProjectRequest):
    # 1. Generate a unique SAP-style project ID
    project_id = generate_project_id(request.series_prefix)

    # 2. Classify project type from name + description
    project_type, confidence = classify_project(
        project_name=request.project_name,
        description=request.description,
    )

    # 3. Generate the WBS (LLM → type-specific fallback)
    plan = generate_wbs(
        project_name=request.project_name,
        description=request.description,
        project_type=project_type,
        total_budget=request.total_budget,
        project_id=project_id,
    )

    # 4. Serialise and return — include classification metadata
    return {
        "project_id":   plan.project_id,
        "project_name": plan.project_name,
        "project_type": plan.project_type,
        "type_confidence": confidence,          # 0.0 – 1.0
        "total_budget": plan.total_budget,
        "start_date":   request.start_date,
        "end_date":     None,
        "tasks": [
            task.model_dump() if hasattr(task, "model_dump") else task.dict()
            for task in plan.tasks
        ],
    }