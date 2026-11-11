"""Makes the pysnmp responder fixture available to every test in this folder."""

from snmp_responder import snmp_responder

__all__ = ["snmp_responder"]
