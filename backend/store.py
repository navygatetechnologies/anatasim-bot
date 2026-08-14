"""In-memory stand-in for the real Controller's `projects.data` (Postgres).

Shaped exactly like `mcp_service/tests/conftest.py`'s `SAMPLE_CONTEXT` /
`SAMPLE_TURBULENCE_CONTEXT` fixtures in the real monorepo -- one seeded demo
project, mutated in place by apply-velocity/apply-setting. No database, no
persistence across restarts: this is a demo, not the real thing.
"""
import copy

DEMO_PROJECT_ID = "demo-project"
DEMO_SIM_ID = "demo-sim"

_SEED = {
    "velocity": {
        "active": "openfoamv2412",
        "mesh_id": "mesh_1",
        "modules": ["fields"],
        "U": {
            "internalField": {"type": "uniform", "value": [0, 0, 0]},
            "inlet": {"type": "fixedValue", "value": [1, 0, 0]},
            "outlet": {"type": "zeroGradient"},
            "wall": {"type": "noSlip"},
        },
        "targets": [
            {"name": "internalField", "type": "uniform", "value": [0, 0, 0]},
            {"name": "inlet", "type": "fixedValue", "value": [1, 0, 0]},
            {"name": "outlet", "type": "zeroGradient", "value": None},
            {"name": "wall", "type": "noSlip", "value": None},
        ],
    },
    "turbulence": {
        "domain": "turbulence",
        "model": {"type": "RAS", "name": "kEpsilon"},
        "targets": [
            {"name": "Cmu", "value": 0.09, "is_default": True, "min": 0, "max": 1},
            {"name": "C1", "value": 1.44, "is_default": True, "min": 0, "max": 2},
            {"name": "C2", "value": 1.92, "is_default": True, "min": 0, "max": 3},
        ],
    },
}

# Keyed by (project_id, sim_id) -- only the one seeded demo project exists.
_PROJECTS = {(DEMO_PROJECT_ID, DEMO_SIM_ID): copy.deepcopy(_SEED)}


class NotFound(Exception):
    pass


class InvalidTarget(Exception):
    pass


def _project(project_id: str, sim_id: str) -> dict:
    project = _PROJECTS.get((project_id, sim_id))
    if project is None:
        raise NotFound(f"no such project/sim: {project_id}/{sim_id}")
    return project


def get_velocity_context(project_id: str, sim_id: str) -> dict:
    return copy.deepcopy(_project(project_id, sim_id)["velocity"])


def apply_velocity(project_id: str, sim_id: str, target: str, value: list) -> None:
    velocity = _project(project_id, sim_id)["velocity"]
    targets = {t["name"]: t for t in velocity["targets"]}
    if target not in targets:
        raise InvalidTarget(
            f"'{target}' is not a valid velocity target. "
            f"Valid targets: {', '.join(targets)}"
        )
    targets[target]["type"] = "fixedValue"
    targets[target]["value"] = value
    velocity["U"][target] = {"type": "fixedValue", "value": value}


def get_setting_context(project_id: str, sim_id: str, domain: str) -> dict:
    project = _project(project_id, sim_id)
    if domain not in project:
        raise InvalidTarget(f"unknown domain '{domain}' -- only 'turbulence' is supported here")
    return copy.deepcopy(project[domain])


def apply_setting(project_id: str, sim_id: str, domain: str, target: str, value) -> None:
    project = _project(project_id, sim_id)
    if domain not in project:
        raise InvalidTarget(f"unknown domain '{domain}' -- only 'turbulence' is supported here")
    targets = {t["name"]: t for t in project[domain]["targets"]}
    if target not in targets:
        raise InvalidTarget(
            f"'{target}' is not a valid {domain} target. "
            f"Valid targets: {', '.join(targets)}"
        )
    targets[target]["value"] = value
    targets[target]["is_default"] = False
