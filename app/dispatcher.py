"""Part 4 student implementation."""

from app.backends import ansible, netconf, netmiko_textfsm, restconf

def dispatch_request(data):
    method = data["method"]
    action = data["action"]
    router = data["router"]
    interface = data["desired"]["interface"]

    if method == "restconf":
        backend = restconf
    elif method == "netconf":
        backend = netconf
    elif method == "ansible":
        backend = ansible
    elif method == "netmiko-textfsm":
        backend = netmiko_textfsm
    else:
        return {"status": "error", "result": "invalid_method"}

    if action == "status" and hasattr(backend, "get_interface_state"):
        return backend.get_interface_state(router, interface["name"])
    if action == "plan" and hasattr(backend, "plan_interface"):
        return backend.plan_interface(router, interface)
    if action == "apply" and hasattr(backend, "apply_interface"):
        return backend.apply_interface(router, interface)
    if action == "delete" and hasattr(backend, "delete_interface"):
        return backend.delete_interface(router, interface["name"])
    return {"status": "error", "result": "invalid_action"}
