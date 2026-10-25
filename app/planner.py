def build_plan(desired_interface, current_interface):
    """
    Compare desired interface state with normalized current state
    and return a plan according to specs/plan-spec-v1.md.
    """
    managed_fields = ("ipv4", "description", "admin_state")
    changes = {}

    if current_interface is None:
        operation = "create"
        changes = {
            field: {"to": desired_interface[field]}
            for field in managed_fields
        }
    else:
        for field in managed_fields:
            old_value = current_interface[field]
            new_value = desired_interface[field]
            if old_value != new_value:
                changes[field] = {
                    "from": old_value,
                    "to": new_value,
                }
        operation = "update" if changes else "no_change"

    return {
        "status": "ok",
        "result": "planned",
        "operation": operation,
        "changes": changes,
    }
