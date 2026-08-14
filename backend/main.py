"""Fake Controller: a tiny stand-in for the real Controller's
`/ai-api/internal/*` routes (`controller/app/api/routes/ai_api.py` +
`app/services/ai_service.py` in the real monorepo) plus of_preprocess's two
schema-grounding routes, merged into one small FastAPI app since this demo
has no reason to run them as separate services. Backed by `store.py`'s
in-memory dict instead of Postgres -- no DB, no auth beyond the same shared-
secret header check the real services use.
"""
import os

from fastapi import FastAPI, Header, HTTPException

import store

WORKER_API_KEY = os.getenv("WORKER_API_KEY", "demo-worker-key")
PREPROCESSOR_API_KEY = os.getenv("PREPROCESSOR_API_KEY", "demo-preprocessor-key")

app = FastAPI(title="ANANTASIM chat demo -- fake backend")


def _verify_worker(x_worker_key: str) -> None:
    if x_worker_key != WORKER_API_KEY:
        raise HTTPException(status_code=401, detail="bad X-Worker-Key")


def _verify_preprocessor(x_controller_key: str) -> None:
    if x_controller_key != PREPROCESSOR_API_KEY:
        raise HTTPException(status_code=401, detail="bad X-Controller-Key")


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------- Controller: projects.data (velocity/turbulence) ---------------- #

@app.get("/ai-api/internal/velocity-context")
def velocity_context(project_id: str, sim_id: str, user_id: str, x_worker_key: str = Header(default="")):
    _verify_worker(x_worker_key)
    try:
        return store.get_velocity_context(project_id, sim_id)
    except store.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/ai-api/internal/apply-velocity")
def apply_velocity(body: dict, x_worker_key: str = Header(default="")):
    _verify_worker(x_worker_key)
    project_id, sim_id = body["project_id"], body["sim_id"]
    target, value = body["target"], body["value"]
    try:
        store.apply_velocity(project_id, sim_id, target, value)
    except store.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except store.InvalidTarget as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "target": target, "value": value, "regenerated": f"{sim_id}/0/U"}


@app.get("/ai-api/internal/setting-context")
def setting_context(project_id: str, sim_id: str, user_id: str, domain: str,
                    x_worker_key: str = Header(default="")):
    _verify_worker(x_worker_key)
    try:
        return store.get_setting_context(project_id, sim_id, domain)
    except store.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except store.InvalidTarget as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/ai-api/internal/apply-setting")
def apply_setting(body: dict, x_worker_key: str = Header(default="")):
    _verify_worker(x_worker_key)
    project_id, sim_id, domain = body["project_id"], body["sim_id"], body["domain"]
    target, value = body["target"], body["value"]
    try:
        store.apply_setting(project_id, sim_id, domain, target, value)
    except store.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except store.InvalidTarget as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "status": "success", "domain": domain, "target": target, "value": value,
        "regenerated": f"{sim_id}/constant/turbulenceProperties",
    }


# ---------------- of_preprocess: schema grounding ---------------- #

@app.get("/fields/{field_name}")
def field_schema(field_name: str, x_controller_key: str = Header(default="")):
    _verify_preprocessor(x_controller_key)
    # Best-effort stub -- the real of_preprocess returns a full field schema;
    # OpenFoamAdapter.enrich_context wraps its call in try/except and works
    # fine with an empty `data`.
    return {"field_name": field_name, "data": {}}


@app.get("/bc/types/all")
def bc_types(x_controller_key: str = Header(default="")):
    _verify_preprocessor(x_controller_key)
    return {"types": []}
