"""What kind of thing a plugin handles or is."""

from enum import StrEnum


class PluginType(StrEnum):
    ROUTER = "router"
    SWITCH = "switch"
    ACCESS_POINT = "access_point"
    FIREWALL = "firewall"
    MODEM = "modem"
    SERVER = "server"
    NAS = "nas"
    COMPUTER = "computer"
    TV = "tv"
    PRINTER = "printer"
    CAMERA = "camera"
    UPS = "ups"
    IOT = "iot"
    SOFTWARE = "software"
    OTHER = "other"
