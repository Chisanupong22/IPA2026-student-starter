import ipaddress
import os
import re

from netmiko import ConnectHandler


def _error(result):
    return {"status": "error", "result": result}


def _map_exception(error):
    name = error.__class__.__name__.lower()
    if isinstance(error, PermissionError) or "auth" in name:
        return "authentication_failed"
    if isinstance(error, (ConnectionError, TimeoutError, OSError)) or any(
        marker in name for marker in ("timeout", "ssh", "connection")
    ):
        return "connection_failed"
    return "backend_failed"


def _connection(router):
    return ConnectHandler(
        device_type="cisco_ios",
        host=router,
        username=os.getenv("ROUTER_USER", ""),
        password=os.getenv("ROUTER_PASS", ""),
        conn_timeout=10,
        banner_timeout=10,
        auth_timeout=10,
    )


def _short_interface_name(interface_name):
    if interface_name.startswith("Loopback"):
        return f"Lo{interface_name[len('Loopback'):]}"
    return interface_name


def _netmiko_get(router, interface_name):
    with _connection(router) as connection:
        ip_info = connection.send_command(
            "show ip interface brief",
            use_textfsm=True,
        )
        descriptions = connection.send_command(
            "show interfaces description",
            use_textfsm=True,
        )
        target_names = (interface_name, _short_interface_name(interface_name))
        row = next(
            (
                item for item in ip_info
                if item.get("interface") in target_names
            ),
            None,
        ) if isinstance(ip_info, list) else None
        if row is not None and not row.get("prefix_length"):
            config = connection.send_command(
                f"show running-config interface {interface_name}"
            )
            match = re.search(
                r"^\s*ip address\s+(\d+(?:\.\d+){3})\s+(\d+(?:\.\d+){3})",
                config,
                re.MULTILINE,
            )
            if match:
                interface = ipaddress.IPv4Interface(
                    f"{match.group(1)}/{match.group(2)}"
                )
                row["ip_address"] = [str(interface.ip)]
                row["prefix_length"] = [str(interface.network.prefixlen)]
    return ip_info, descriptions


def _normalize_netmiko_state(interface_name, ip_info, descriptions):
    short_name = _short_interface_name(interface_name)
    row = next(
        (
            item for item in ip_info
            if item.get("interface") in (interface_name, short_name)
        ),
        None,
    )
    description_row = next(
        (
            item for item in descriptions
            if item.get("port") in (interface_name, short_name)
        ),
        None,
    )
    if row is None and description_row is None:
        return None

    ip_address = row.get("ip_address", []) if row else []
    prefix_length = row.get("prefix_length", []) if row else []
    address = ip_address[0] if ip_address else None
    prefix = prefix_length[0] if prefix_length else None
    link_status = row.get("link_status", "") if row else ""
    protocol_status = row.get("protocol_status", "") if row else ""
    status = (
        f"{link_status} {protocol_status} "
        f"{description_row.get('status', '') if description_row else ''}"
    ).lower()
    return {
        "name": interface_name,
        "ipv4": f"{address}/{prefix}" if address and prefix else None,
        "description": (
            description_row.get("description", "") if description_row else ""
        ),
        "admin_state": "down" if "down" in status else "up",
    }


def get_interface_state(
    router,
    interface_name,
    netmiko_get=None,
):
    """Return normalized interface status using Netmiko + TextFSM."""
    try:
        ip_info, descriptions = (netmiko_get or _netmiko_get)(
            router,
            interface_name,
        )
        interface = _normalize_netmiko_state(
            interface_name,
            ip_info,
            descriptions,
        )
        if interface is None:
            return {"status": "ok", "result": "not_found", "interface": None}
        return {"status": "ok", "result": "found", "interface": interface}
    except Exception as error:
        return _error(_map_exception(error))


def delete_interface(
    router,
    interface_name,
    netmiko_delete=None,
):
    """Delete an interface using Netmiko."""
    try:
        if netmiko_delete is not None:
            result = netmiko_delete(router, interface_name)
            if result == "not_found":
                return {"status": "ok", "result": "not_found", "interface": None}
            if result == "deleted":
                return {"status": "ok", "result": "deleted"}
            return _error("backend_failed")

        current = get_interface_state(router, interface_name)
        if current["status"] == "error":
            return current
        if current["result"] == "not_found":
            return current

        with _connection(router) as connection:
            output = connection.send_config_set([f"no interface {interface_name}"])
        if "% Invalid" in output or "% Incomplete" in output or "% Ambiguous" in output:
            return _error("backend_failed")

        verified = get_interface_state(router, interface_name)
        if verified["status"] == "error":
            return verified
        if verified["result"] == "not_found":
            return {"status": "ok", "result": "deleted"}
        return _error("backend_failed")
    except Exception as error:
        return _error(_map_exception(error))
