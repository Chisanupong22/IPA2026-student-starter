import ipaddress
import os

import requests

from app.backends.planning import plan_interface as build_backend_plan


def _error(result):
    return {"status": "error", "result": result}


def _map_exception(error):
    if isinstance(error, PermissionError) or error.__class__.__name__ in {
        "AuthenticationError",
        "AuthenticationException",
    }:
        return "authentication_failed"
    if isinstance(error, (ConnectionError, TimeoutError, requests.exceptions.Timeout,
                          requests.exceptions.ConnectionError)) or error.__class__.__name__ in {
        "ConnectTimeout",
        "ReadTimeout",
    }:
        return "connection_failed"
    return "backend_failed"


def _interface_number(interface_name):
    prefix = "Loopback"
    if not interface_name.startswith(prefix):
        raise ValueError("RESTCONF supports Loopback interfaces only")
    number = int(interface_name[len(prefix):])
    if number < 0:
        raise ValueError("Loopback number must not be negative")
    return number


def _base_url(router):
    return f"https://{router}/restconf/data"


def _get(url, http_get):
    if http_get is not None:
        return http_get(url)
    return requests.get(
        url,
        auth=(os.getenv("ROUTER_USER", ""), os.getenv("ROUTER_PASS", "")),
        headers={"Accept": "application/yang-data+json"},
        verify=False,
        timeout=10,
    )


def _put(url, payload, http_put):
    if http_put is not None:
        return http_put(url, json=payload)
    return requests.put(
        url,
        json=payload,
        auth=(os.getenv("ROUTER_USER", ""), os.getenv("ROUTER_PASS", "")),
        headers={
            "Accept": "application/yang-data+json",
            "Content-Type": "application/yang-data+json",
        },
        verify=False,
        timeout=10,
    )


def _prefix_from_netmask(netmask):
    return ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen


def get_interface_state(
    router,
    interface_name,
    http_get=None,
):
    """Return normalized interface status using RESTCONF."""
    try:
        url = (
            f"{_base_url(router)}/ietf-interfaces:interfaces/"
            f"interface={interface_name}"
        )
        response = _get(url, http_get)
        if response.status_code == 404:
            return {"status": "ok", "result": "not_found", "interface": None}
        if response.status_code in (401, 403):
            return _error("authentication_failed")
        if response.status_code < 200 or response.status_code >= 300:
            return _error("backend_failed")

        payload = response.json()
        interface = payload.get("ietf-interfaces:interface")
        if isinstance(interface, list):
            interface = next(
                (item for item in interface if item.get("name") == interface_name),
                None,
            )
        if not isinstance(interface, dict):
            return {"status": "ok", "result": "not_found", "interface": None}

        ipv4 = interface.get("ietf-ip:ipv4", {}).get("address", [])
        address = ipv4[0] if ipv4 else {}
        admin_state = "down" if interface.get("enabled", True) in (False, "false") else "up"
        return {
            "status": "ok",
            "result": "found",
            "interface": {
                "name": interface.get("name", interface_name),
                "ipv4": f"{address['ip']}/{_prefix_from_netmask(address['netmask'])}"
                if address.get("ip") and address.get("netmask")
                else None,
                "description": interface.get("description", ""),
                "admin_state": admin_state,
            },
        }
    except Exception as error:
        return _error(_map_exception(error))


def plan_interface(
    router,
    desired_interface,
    http_get=None,
):
    """Return create/update/no_change plan using RESTCONF status."""
    return build_backend_plan(
        router,
        desired_interface,
        lambda target_router, name: get_interface_state(target_router, name, http_get),
    )


def apply_interface(
    router,
    desired_interface,
    http_put=None,
):
    """Apply complete desired interface state using RESTCONF."""
    try:
        number = _interface_number(desired_interface["name"])
        address = ipaddress.IPv4Interface(desired_interface["ipv4"])
        payload = {
            "Cisco-IOS-XE-native:Loopback": {
                "name": number,
                "description": desired_interface["description"],
                "ip": {
                    "address": {
                        "primary": {
                            "address": str(address.ip),
                            "mask": str(address.network.netmask),
                        }
                    }
                },
            }
        }
        if desired_interface["admin_state"] == "down":
            payload["Cisco-IOS-XE-native:Loopback"]["shutdown"] = [None]
        url = (
            f"{_base_url(router)}/Cisco-IOS-XE-native:native/interface/"
            f"Loopback={number}"
        )
        response = _put(url, payload, http_put)
        if response.status_code in (401, 403):
            return _error("authentication_failed")
        if response.status_code < 200 or response.status_code >= 300:
            return _error("backend_failed")
        return {"status": "ok", "result": "applied"}
    except Exception as error:
        return _error(_map_exception(error))
