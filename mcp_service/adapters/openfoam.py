import controller_client
from adapters.base import SolverAdapter


class OpenFoamAdapter(SolverAdapter):

    def enrich_context(self, context: dict) -> dict:
        # Grounding from the schema endpoint is best-effort -- the project
        # data in `context` is already enough to act on.
        try:
            field_schema = controller_client.get_field_schema("U")
        except Exception:
            field_schema = None

        context["field"] = {
            "name": "U",
            "dictionary_file": "0/U",
            "schema": field_schema,
        }
        context["note"] = (
            "Velocity is the OpenFOAM field 'U', written to dictionary file 0/U. "
            "Only the entries listed in 'targets' can be changed. Setting a patch "
            "velocity overwrites that patch's boundary type to fixedValue."
        )
        return context

    def apply_change(self, project_id: str, sim_id: str, user_id: str,
                     target: str, value: list[float]) -> dict:
        return controller_client.apply_velocity(project_id, sim_id, user_id, target, value)
