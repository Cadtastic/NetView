"""Per-device traffic, signal and names from a Starlink router local API.

Install it by copying this folder into the plugins folder of your netview data directory.
"""

from .plugin import StarlinkPlugin

plugin_class = StarlinkPlugin
