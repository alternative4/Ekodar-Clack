"""Constants for the Clack Ekodar (local MQTT) integration."""

DOMAIN = "clack_ekodar"

CONF_MAC = "mac"
CONF_PREFIX = "prefix"
CONF_SECTION_INTERVAL = "section_interval"

DEFAULT_PREFIX = "OE/171"
DEFAULT_SECTION_INTERVAL_MIN = 60

CONTROL_TOPIC_SUFFIX = "/deviceControl"

# settings sections (unit: deviceControl {"command":200,"section":N})
SECTION_INSTALLER = 201
SECTION_SERVICE = 202
SECTION_CONFIG = 203
SECTION_REGEN = 206
SECTION_TIME = 208
SECTION_CODES = (SECTION_INSTALLER, SECTION_SERVICE, SECTION_CONFIG,
                 SECTION_REGEN, SECTION_TIME)

CMD_IDLE = 100
CMD_REGEN = 110
CMD_REGENERATE = 111
CMD_REBOOT = 113
CMD_SET_INSTALLER = 201
CMD_SET_TIME = 208

ONLINE_TIMEOUT_S = 120  # device sends status every ~30 s

DAY_NAMES_EN = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]
