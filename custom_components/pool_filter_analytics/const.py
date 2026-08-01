"""Constants for Pool Filter Analytics."""

from typing import Final

DOMAIN: Final = "pool_filter_analytics"

CONF_SOURCE_ENTITY: Final = "source_entity"
CONF_OFFLINE_THRESHOLD: Final = "offline_threshold"
CONF_MINIMUM_DROP: Final = "minimum_drop"
CONF_SAMPLE_INTERVAL: Final = "sample_interval"

DEFAULT_OFFLINE_THRESHOLD: Final = 2.0
DEFAULT_MINIMUM_DROP: Final = 0.5
DEFAULT_SAMPLE_INTERVAL: Final = 300

STATE_NORMAL: Final = "normal"
STATE_AWAITING_RESTART: Final = "awaiting_restart"
STATE_RECOVERING: Final = "recovering"

STORAGE_VERSION: Final = 1
