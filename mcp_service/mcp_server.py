from typing import Union

from mcp.server.fastmcp import FastMCP

import controller_client
from adapters.registry import get_adapter

# stateless_http: conversation state lives client-side. The protocol is
# served at the default /mcp path; main.py mounts the MCP app at root so no
# trailing-slash redirect is emitted (MCP clients do not follow 307s).
mcp = FastMCP(
    "anantasim-sim-assistant-demo",
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def get_velocity_context(project_id: str, sim_id: str, user_id: str) -> dict:
    """Get the current velocity (U) configuration of a simulation: the
    internal field and every boundary patch, with their types and values.
    Always call this before changing or discussing velocity -- its `targets`
    list is the complete set of valid targets for set_velocity."""
    context = controller_client.get_velocity_context(project_id, sim_id, user_id)
    return get_adapter(context["active"]).enrich_context(context)


@mcp.tool()
def set_velocity(project_id: str, sim_id: str, user_id: str,
                 target: str, value: list[float]) -> dict:
    """Set the velocity of one existing target to [x, y, z] in m/s.
    `target` must be 'internalField' or a boundary patch name that appears in
    get_velocity_context's `targets` -- new targets cannot be created."""
    context = controller_client.get_velocity_context(project_id, sim_id, user_id)
    return get_adapter(context["active"]).apply_change(
        project_id, sim_id, user_id, target, value
    )


# ---------------- Generic setting tools (velocity + turbulence) ----------------
#
# One get/apply pair instead of one per parameter. The backend already
# resolves each domain against its own schemas, so this stays a thin
# pass-through -- no per-solver adapter dispatch is needed here.

@mcp.tool()
def get_setting_context(project_id: str, sim_id: str, user_id: str, domain: str) -> dict:
    """Get every editable target in a domain ('velocity' or 'turbulence') with
    its current value. For 'turbulence', targets still left on the platform's
    default (never explicitly set by the user) are included too, with
    `is_default: true` -- always call this before changing or discussing a
    turbulence coefficient, since its `targets` list is the complete set of
    valid targets for apply_setting."""
    return controller_client.get_setting_context(project_id, sim_id, user_id, domain)


@mcp.tool()
def apply_setting(project_id: str, sim_id: str, user_id: str, domain: str, target: str,
                  value: Union[float, str, list[float]]) -> dict:
    """Set one existing target in a domain ('velocity' or 'turbulence') to a
    new value. `target` must be one of get_setting_context's `targets` for
    that domain -- new targets/coefficients cannot be invented. For
    'turbulence', this is also how you change a coefficient that is still on
    its platform default (is_default: true) -- the value just hasn't been
    written to the project yet."""
    return controller_client.apply_setting(project_id, sim_id, user_id, domain, target, value)
