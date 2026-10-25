from collections.abc import Mapping
from pathlib import Path

import yaml


ALLOWED_ROUTERS = {
    "10.0.29.101",
    "10.0.29.102",
    "10.0.29.103",
    "10.0.29.104",
    "10.0.29.105",
}
SUPPORTED_ACTIONS = {
    "restconf": {"status", "plan", "apply"},
    "netconf": {"status", "plan", "apply"},
    "ansible": {"apply"},
    "netmiko-textfsm": {"status", "delete"},
}


def _error(result):
    return {"status": "error", "result": result}


def validate_request(data):
    """
    Validate one IPA2026 desired-state request.

    Return a response dictionary according to
    specs/response-spec-v1.md.
    """
    if not isinstance(data, Mapping):
        return _error("invalid_yaml")

    version = data.get("version")
    if type(version) is not int or version != 1:
        return _error("invalid_version")

    if "router" not in data or data["router"] in (None, ""):
        return _error("missing_router")
    if not isinstance(data["router"], str) or data["router"] not in ALLOWED_ROUTERS:
        return _error("invalid_router")

    if "method" not in data or data["method"] in (None, ""):
        return _error("missing_method")
    method = data["method"]
    if not isinstance(method, str):
        return _error("invalid_method")
    if method not in SUPPORTED_ACTIONS:
        return _error("invalid_method")

    if "action" not in data or data["action"] in (None, ""):
        return _error("missing_action")
    action = data["action"]
    if not isinstance(action, str):
        return _error("invalid_action")
    if action not in SUPPORTED_ACTIONS[method]:
        return _error("invalid_action")

    if "desired" not in data or data["desired"] is None:
        return _error("missing_desired")
    desired = data["desired"]
    if not isinstance(desired, Mapping) or "interface" not in desired or desired["interface"] is None:
        return _error("missing_interface")
    interface = desired["interface"]
    if not isinstance(interface, Mapping) or "name" not in interface or interface["name"] in (None, ""):
        return _error("missing_interface_name")

    if action in {"plan", "apply"}:
        for field, error in (
            ("ipv4", "missing_ipv4"),
            ("description", "missing_description"),
            ("admin_state", "missing_admin_state"),
        ):
            if field not in interface or interface[field] in (None, ""):
                return _error(error)
        if not isinstance(interface["admin_state"], str) or interface["admin_state"] not in {"up", "down"}:
            return _error("invalid_admin_state")

    return {"status": "ok", "result": "accepted"}


def process_request_file(path):
    """
    Read a YAML request file, validate it,
    and return a response dictionary.
    """
    try:
        with Path(path).open(encoding="utf-8") as request_file:
            data = yaml.safe_load(request_file)
    except (OSError, UnicodeError, yaml.YAMLError):
        return _error("invalid_yaml")
    return validate_request(data)
