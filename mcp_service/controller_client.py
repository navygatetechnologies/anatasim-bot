import time

import requests

import config
from logger import get_logger

log = get_logger(__name__)


class ControllerError(Exception):
    """Raised with the upstream error detail so the agent's LLM can read it."""


def _request(method: str, url: str, **kwargs):
    start = time.monotonic()
    response = requests.request(method, url, timeout=30, **kwargs)
    duration_ms = round((time.monotonic() - start) * 1000)

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        log.error(
            "backend_error",
            method=method,
            url=url,
            status=response.status_code,
            detail=detail,
            duration_ms=duration_ms,
        )
        raise ControllerError(f"{response.status_code}: {detail}")

    log.info(
        "backend_request",
        method=method,
        url=url,
        status=response.status_code,
        duration_ms=duration_ms,
    )
    return response.json()


def _service_headers():
    return {"X-Worker-Key": config.WORKER_API_KEY}


def _preprocessor_headers():
    return {"X-Controller-Key": config.PREPROCESSOR_API_KEY}


# ---------------- backend/: projects.data source of truth ---------------- #

def get_velocity_context(project_id: str, sim_id: str, user_id: str):
    return _request(
        "GET",
        f"{config.BACKEND_HOST}/ai-api/internal/velocity-context",
        params={"project_id": project_id, "sim_id": sim_id, "user_id": user_id},
        headers=_service_headers(),
    )


def apply_velocity(project_id: str, sim_id: str, user_id: str,
                   target: str, value: list[float]):
    return _request(
        "POST",
        f"{config.BACKEND_HOST}/ai-api/internal/apply-velocity",
        json={
            "project_id": project_id,
            "sim_id": sim_id,
            "user_id": user_id,
            "target": target,
            "value": value,
        },
        headers=_service_headers(),
    )


def get_setting_context(project_id: str, sim_id: str, user_id: str, domain: str):
    return _request(
        "GET",
        f"{config.BACKEND_HOST}/ai-api/internal/setting-context",
        params={"project_id": project_id, "sim_id": sim_id, "user_id": user_id, "domain": domain},
        headers=_service_headers(),
    )


def apply_setting(project_id: str, sim_id: str, user_id: str, domain: str, target: str, value):
    return _request(
        "POST",
        f"{config.BACKEND_HOST}/ai-api/internal/apply-setting",
        json={
            "project_id": project_id,
            "sim_id": sim_id,
            "user_id": user_id,
            "domain": domain,
            "target": target,
            "value": value,
        },
        headers=_service_headers(),
    )


# ---------------- backend/: schema-grounding endpoints ---------------- #

def get_field_schema(field_name: str):
    return _request(
        "GET", f"{config.BACKEND_HOST}/fields/{field_name}", headers=_preprocessor_headers()
    )


def get_bc_types():
    return _request(
        "GET", f"{config.BACKEND_HOST}/bc/types/all", headers=_preprocessor_headers()
    )
