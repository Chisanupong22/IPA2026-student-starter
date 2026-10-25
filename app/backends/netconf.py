import ipaddress
import os
import xml.etree.ElementTree as ET

from app.backends.planning import plan_interface as build_backend_plan


NETCONF_NS = "urn:ietf:params:xml:ns:netconf:base:1.0"
NATIVE_NS = "http://cisco.com/ns/yang/Cisco-IOS-XE-native"
IETF_NS = "urn:ietf:params:xml:ns:yang:ietf-interfaces"
IP_NS = "urn:ietf:params:xml:ns:yang:ietf-ip"


def _error(result):
    return {"status": "error", "result": result}


def _map_exception(error):
    name = error.__class__.__name__.lower()
    if isinstance(error, PermissionError) or "auth" in name:
        return "authentication_failed"
    if isinstance(error, (ConnectionError, TimeoutError, OSError)) or any(
        marker in name for marker in ("timeout", "session", "ssh", "transport")
    ):
        return "connection_failed"
    return "backend_failed"


def _call_get(router, filter_xml, netconf_get_config):
    if netconf_get_config is not None:
        return netconf_get_config(router, filter_xml)
    from ncclient import manager

    with manager.connect(
        host=router,
        port=int(os.getenv("NETCONF_PORT", "830")),
        username=os.getenv("ROUTER_USER", ""),
        password=os.getenv("ROUTER_PASS", ""),
        hostkey_verify=False,
        timeout=10,
        allow_agent=False,
        look_for_keys=False,
    ) as session:
        return session.get_config(source="running", filter=("subtree", filter_xml)).data_xml


def _xml_text(element, namespace, name):
    child = element.find(f"{{{namespace}}}{name}")
    return child.text.strip() if child is not None and child.text else None


def _normalized_interface(xml_text, interface_name):
    root = ET.fromstring(xml_text)
    interface = next(
        (
            element for element in root.iter()
            if element.tag.split("}")[-1] == "interface"
            and _xml_text(element, IETF_NS, "name") == interface_name
        ),
        None,
    )
    if interface is None:
        return None

    description = _xml_text(interface, IETF_NS, "description")
    enabled = _xml_text(interface, IETF_NS, "enabled")
    ipv4 = interface.find(f"{{{IP_NS}}}ipv4")
    address = ipv4.find(f"{{{IP_NS}}}address") if ipv4 is not None else None
    ip_value = _xml_text(address, IP_NS, "ip") if address is not None else None
    netmask = _xml_text(address, IP_NS, "netmask") if address is not None else None
    shutdown = any(
        element.tag.split("}")[-1] == "shutdown"
        for element in interface.iter()
    )
    state = "down" if shutdown or enabled == "false" else "up"
    ipv4_value = None
    if ip_value and netmask:
        ipv4_value = f"{ip_value}/{ipaddress.IPv4Network(f'0.0.0.0/{netmask}').prefixlen}"
    return {
        "name": interface_name,
        "ipv4": ipv4_value,
        "description": description or "",
        "admin_state": state,
    }


def get_interface_state(
    router,
    interface_name,
    netconf_get_config=None,
):
    """Return normalized interface status using NETCONF."""
    filter_xml = (
        f'<interfaces xmlns="{IETF_NS}"><interface>'
        f"<name>{interface_name}</name></interface></interfaces>"
    )
    try:
        response = _call_get(router, filter_xml, netconf_get_config)
        if hasattr(response, "data_xml"):
            response = response.data_xml
        interface = _normalized_interface(response, interface_name)
        if interface is None:
            return {"status": "ok", "result": "not_found", "interface": None}
        return {"status": "ok", "result": "found", "interface": interface}
    except Exception as error:
        return _error(_map_exception(error))


def plan_interface(
    router,
    desired_interface,
    netconf_get_config=None,
):
    """Return create/update/no_change plan using NETCONF status."""
    return build_backend_plan(
        router,
        desired_interface,
        lambda target_router, name: get_interface_state(
            target_router,
            name,
            netconf_get_config,
        ),
    )


def apply_interface(
    router,
    desired_interface,
    netconf_edit_config=None,
):
    """Apply complete desired interface state using NETCONF."""
    try:
        number = int(desired_interface["name"].removeprefix("Loopback"))
        address = ipaddress.IPv4Interface(desired_interface["ipv4"])
        root = ET.Element("config", {"xmlns": NETCONF_NS})
        native = ET.SubElement(root, f"{{{NATIVE_NS}}}native")
        interfaces = ET.SubElement(native, f"{{{NATIVE_NS}}}interface")
        loopback = ET.SubElement(
            interfaces,
            f"{{{NATIVE_NS}}}Loopback",
            {f"{{{NETCONF_NS}}}operation": "replace"},
        )
        ET.SubElement(loopback, f"{{{NATIVE_NS}}}name").text = str(number)
        ET.SubElement(loopback, f"{{{NATIVE_NS}}}description").text = desired_interface["description"]
        ip = ET.SubElement(loopback, f"{{{NATIVE_NS}}}ip")
        ip_address = ET.SubElement(ip, f"{{{NATIVE_NS}}}address")
        primary = ET.SubElement(ip_address, f"{{{NATIVE_NS}}}primary")
        ET.SubElement(primary, f"{{{NATIVE_NS}}}address").text = str(address.ip)
        ET.SubElement(primary, f"{{{NATIVE_NS}}}mask").text = str(address.network.netmask)
        if desired_interface["admin_state"] == "down":
            ET.SubElement(loopback, f"{{{NATIVE_NS}}}shutdown")
        config_xml = ET.tostring(root, encoding="unicode")

        if netconf_edit_config is not None:
            result = netconf_edit_config(router, config_xml)
        else:
            from ncclient import manager

            with manager.connect(
                host=router,
                port=int(os.getenv("NETCONF_PORT", "830")),
                username=os.getenv("ROUTER_USER", ""),
                password=os.getenv("ROUTER_PASS", ""),
                hostkey_verify=False,
                timeout=10,
                allow_agent=False,
                look_for_keys=False,
            ) as session:
                result = session.edit_config(target="running", config=config_xml)
        if result is not None and getattr(result, "ok", True) is False:
            return _error("backend_failed")
        return {"status": "ok", "result": "applied"}
    except Exception as error:
        return _error(_map_exception(error))
