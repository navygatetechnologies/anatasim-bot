from abc import ABC, abstractmethod


class SolverAdapter(ABC):
    """Solver-specific behaviour behind the generic MCP tools.

    The backend owns the data; adapters only ground the context with
    solver knowledge and route apply calls. Supporting a new solver means
    implementing this and registering it in adapters/registry.py.
    """

    @abstractmethod
    def enrich_context(self, context: dict) -> dict:
        ...

    @abstractmethod
    def apply_change(self, project_id: str, sim_id: str, user_id: str,
                     target: str, value: list[float]) -> dict:
        ...
