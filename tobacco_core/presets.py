from __future__ import annotations

BAND_DEFINITIONS = [
    {"name": "8-9段", "min": 80, "max": 99},
    {"name": "10段", "min": 100, "max": 109},
    {"name": "11段", "min": 110, "max": 119},
    {"name": "12段", "min": 120, "max": 129},
    {"name": "13段", "min": 130, "max": 139},
    {"name": "14-15段", "min": 140, "max": 159},
]

DEFAULT_PRESETS = [
    {
        "id": "tier30",
        "name": "三十档",
        "target_total": 104,
        "supply_total": 166,
        "band_caps": {"8-9段": 25, "10段": 4, "11段": 5, "12段": 32, "13段": 13, "14-15段": 3},
    },
    {
        "id": "tier29",
        "name": "二十九档",
        "target_total": 99,
        "supply_total": 161,
        "band_caps": {"8-9段": 25, "10段": 4, "11段": 5, "12段": 32, "13段": 13, "14-15段": 3},
    },
    {
        "id": "tier28",
        "name": "二十八档",
        "target_total": 92,
        "supply_total": 155,
        "band_caps": {"8-9段": 25, "10段": 4, "11段": 5, "12段": 32, "13段": 12, "14-15段": 3},
    },
    {
        "id": "tier27",
        "name": "二十七档",
        "target_total": 81,
        "supply_total": 138,
        "band_caps": {"8-9段": 23, "10段": 3, "11段": 4, "12段": 28, "13段": 12, "14-15段": 3},
    },
    {
        "id": "tier26",
        "name": "二十六档",
        "target_total": 81,
        "supply_total": 139,
        "band_caps": {"8-9段": 22, "10段": 3, "11段": 4, "12段": 28, "13段": 12, "14-15段": 3},
    },
]
