"""Per-device traffic, signal and names from a Starlink router local API.

Install it by copying this folder into the plugins folder of your NetView data directory.
"""

from .plugin import StarlinkPlugin

plugin_class = StarlinkPlugin
