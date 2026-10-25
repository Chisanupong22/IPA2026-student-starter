import json
import os
import subprocess
from pathlib import Path


def _error(result):
    return {"status": "error", "result": result}


def _map_exception(error):
    name = error.__class__.__name__.lower()
    if isinstance(error, PermissionError) or "auth" in name:
        return "authentication_failed"
    if isinstance(error, (ConnectionError, TimeoutError, OSError)) or any(
        marker in name for marker in ("timeout", "unreachable", "connection")
    ):
        return "connection_failed"
    return "backend_failed"


def _run_playbook(variables):
    app_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.update({
        "ANSIBLE_HOST_KEY_CHECKING": "False",
        "ANSIBLE_PERSISTENT_CONNECT_TIMEOUT": "10",
    })
    complete_variables = {
        **variables,
        "ansible_host": variables["router"],
        "ansible_user": os.getenv("ROUTER_USER", ""),
        "ansible_password": os.getenv("ROUTER_PASS", ""),
    }
    try:
        subprocess.run(
            [
                "ansible-playbook",
                "-i",
                str(app_root / "ansible" / "inventory.ini"),
                str(app_root / "ansible" / "apply_interface.yml"),
                "--extra-vars",
                json.dumps(complete_variables),
            ],
            cwd=app_root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.CalledProcessError as error:
        message = f"{error.stdout or ''}\n{error.stderr or ''}".lower()
        if "authentication" in message or "invalid username" in message or "permission denied" in message:
            raise PermissionError("Ansible authentication failed") from error
        if "unreachable" in message or "timed out" in message or "connection" in message:
            raise ConnectionError("Ansible connection failed") from error
        raise RuntimeError("Ansible playbook failed") from error


def apply_interface(
    router,
    desired_interface,
    run_playbook=None,
):
    """Apply complete desired interface state using Ansible."""
    try:
        address, prefix = desired_interface["ipv4"].split("/", 1)
        import ipaddress

        variables = {
            "router": router,
            "interface_name": desired_interface["name"],
            "description": desired_interface["description"],
            "ipv4_address": address,
            "netmask": str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask),
            "shutdown": desired_interface["admin_state"] == "down",
        }
        (run_playbook or _run_playbook)(variables)
        return {"status": "ok", "result": "applied"}
    except Exception as error:
        return _error(_map_exception(error))
