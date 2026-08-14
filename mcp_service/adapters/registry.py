from adapters.base import SolverAdapter
from adapters.openfoam import OpenFoamAdapter

# Extension point: one entry per supported solver, keyed by the sim entry's
# `active` value.
ADAPTERS: dict[str, SolverAdapter] = {
    "openfoamv2412": OpenFoamAdapter(),
}


def get_adapter(active: str) -> SolverAdapter:
    adapter = ADAPTERS.get(active)
    if adapter is None:
        raise ValueError(
            f"Solver '{active}' is not supported by this demo. "
            f"Supported solvers: {', '.join(ADAPTERS)}"
        )
    return adapter
