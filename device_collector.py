from dataclasses import dataclass, field
from typing import List, Optional

from custom_modules.snmp import SNMPDevice
from custom_modules.errors import Error
from custom_modules.log import logger

@dataclass
class CollectedInterface:
    name: str
    lldp_rem_name: str = ''
    lldp_rem_port: Optional[str] = None

@dataclass
class CollectedDevice:
    nb_name: str
    ip: str
    hostname: str
    model: str
    serial: str
    role: str = ''
    interfaces: List[CollectedInterface] = field(default_factory=list)

def snmp_query_device(nb_device, community_cf, version_cf) -> CollectedDevice:
    """
    Извлекает SNMP-данные из устройства NetBox

    Args:
        nb_device: NetBox устройство
        community_cf: имя custom field для community
        version_cf: имя custom field для версии SNMP

    Returns:
        CollectedDevice: объект с данными устройства
    """
    if not nb_device.primary_ip:
        raise Error('no primary_ip', nb_device.name)

    ip = nb_device.primary_ip.address.split('/')[0]
    community = nb_device.custom_fields.get(community_cf)
    version   = nb_device.custom_fields.get(version_cf)
    if not community or not version:
        raise Error('no SNMP data', nb_device.name)

    logger.info(f"Querying device {nb_device.name} ({ip}) via SNMP")
    snmp = SNMPDevice(ip, community_string=community, version=version)

    cd = CollectedDevice(
        nb_name = nb_device.name,
        ip      = ip,
        hostname= snmp.get_hostname(),
        model   = snmp.get_model(),
        serial  = snmp.get_serial_number(),
        role    = getattr(nb_device.device_role, 'slug', '')  # Получаем роль из NetBox
    )

    interfaces = snmp.get_physical_interfaces()
    logger.info(f"Retrieved {len(interfaces)} interfaces from {nb_device.name}")

    for intf in interfaces:
        if hasattr(intf, 'lldp_rem') and intf.lldp_rem.get('name'):
            cd.interfaces.append(
                CollectedInterface(
                    name = intf.name,
                    lldp_rem_name  = intf.lldp_rem['name'],
                    lldp_rem_port  = intf.lldp_rem.get('port')
                )
            )

    logger.debug(f"Found {len(cd.interfaces)} interfaces with LLDP data on {nb_device.name}")
    return cd