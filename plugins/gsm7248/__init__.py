"""The GSM7248 switch plugin (read-only SNMP monitoring, plus the serial console).

Install it by copying this folder into the plugins folder of your netview data directory.
"""

from .plugin import Gsm7248Plugin

plugin_class = Gsm7248Plugin
