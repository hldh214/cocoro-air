"""Sharp purifier commands and measurements, independent of Home Assistant.

The wire format and boundaries follow the official COCORO AIR web application.
Limit markers are exposed as status strings, never as numeric measurements.
"""
from __future__ import annotations

from typing import Any

MODE_CODES = {
    "ai_auto": "20", "auto": "10", "pollen": "13", "sleep": "11",
    "feel": "40", "splash": "30", "quiet": "14", "medium": "15",
    "strong": "16", "weak": "1B", "rapid": "1C", "turbo": "1A",
}
STATUS_MODES = {
    **{code: name for name, code in MODE_CODES.items()},
    "00": "off", "02": "settings", "0D": "humidifier_cleaning",
    "0E": "cleaning_stopped", "0F": "error", "18": "odor_patrol",
    "1E": "cleaning", "50": "powerful_shot", "60": "cleaning_assist",
    "80": "demo", "FF": "special",
}
AI_SUBMODES = {
    "81": "dog", "82": "dog", "83": "cat", "84": "cat",
    "0D": "ai_humidity_measurement", "20": "custom",
    "10": "purification_cooperation", "11": "circulation_cooperation",
}


def _hex(value: Any) -> int | None:
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return None


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()
                if isinstance(key, str) and key.startswith("s") and key[1:].isdigit()}
    if isinstance(value, str):
        return value.removeprefix("0x").removeprefix("0X").upper()
    return value


def _measurement(value: int | None, low: int, high: int) -> tuple[int | None, str]:
    if value is None:
        return None, "unknown"
    if value <= low:
        return None, "low"
    if value >= high:
        return None, "high"
    return value, "normal"


def parse_status(body: dict, spec: dict) -> dict:
    """Merge property rows and return flat, capability-aware entity state.

    ``properties`` contains only normalized k1/k2/k3 and EPC 80/86, suitable
    for advanced services. No device identifiers or account fields are retained.
    """
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ValueError("Invalid purifier status: expected a property row list")
    properties: dict[str, Any] = {}
    last_update = None
    for row in body["data"]:
        if not isinstance(row, dict):
            raise ValueError("Invalid purifier status: expected a property row object")
        if isinstance(row.get("time"), str) and row["time"]:
            last_update = max(last_update or row["time"], row["time"])
        for key, value in row.items():
            if not isinstance(key, str):
                continue
            normalized_key = key.removeprefix("0x").removeprefix("0X")
            if normalized_key not in ("k1", "k2", "k3", "80", "86"):
                continue
            if normalized_key in ("k1", "k2", "k3") and not isinstance(value, dict):
                raise ValueError("Invalid purifier status: expected a property section object")
            if normalized_key == "86" and not isinstance(value, str):
                raise ValueError("Invalid purifier status: expected a fault property string")
            normalized = _normalize(value)
            if isinstance(normalized, dict):
                properties.setdefault(normalized_key, {}).update(normalized)
            else:
                properties[normalized_key] = normalized
    k1, k2, k3 = (properties.get(key, {}) for key in ("k1", "k2", "k3"))
    mode = _hex(k3.get("s1"))
    stopped = mode is None or mode & 0xF0 == 0 or mode == 0x1E
    power_raw = _hex(properties.get("80"))
    power = True if mode in (0x0E, 0x1E) else (
        power_raw == 0x30 if power_raw in (0x30, 0x31) else None)
    cloud_raw = _hex(k3.get("s2"))
    cloud_enabled = None if cloud_raw is None or not spec.get("hasCloudService") else bool(cloud_raw & 0x80)
    current_mode = STATUS_MODES.get(k3.get("s1"), "unknown")
    if mode == 0x20:
        current_mode = AI_SUBMODES.get(k3.get("s10"), "ai_auto")
        if current_mode == "cat" and k3.get("s9") == "FF":
            current_mode = "cat_child_lock"

    temp = None if stopped else _hex(k1.get("s1"))
    if temp is None:
        temperature, temperature_status = None, "unknown"
    elif temp >= 128:
        temperature, temperature_status = None, "low"
    elif temp >= 51:
        temperature, temperature_status = None, "high"
    else:
        temperature, temperature_status = temp, "normal"
    humidity, humidity_status = _measurement(
        None if stopped else _hex(k1.get("s2")),
        24 if spec.get("seriiesCode", 0) >= 6 else 6,
        76 if spec.get("seriiesCode", 0) >= 6 else 100,
    )
    pm_raw = None if stopped else _hex(k1.get("s7"))
    if not spec.get("hasPM25Sensor"):
        pm25, pm25_status = None, "unsupported"
    elif pm_raw is None:
        pm25, pm25_status = None, "unknown"
    elif pm_raw & 0x8000:
        pm25, pm25_status = None, "measuring"
    else:
        pm25, pm25_status = _measurement(pm_raw & 0x3FF, 0, 500)

    odor = None if stopped else _hex(k2.get("s1"))
    dust = None if stopped or not spec.get("hasDustSensor") else _hex(k2.get("s2"))
    air = None if stopped else _hex(k2.get("s4"))
    odor_level = None if odor is None else sum(odor > limit for limit in (16, 50, 75))
    dust_level = None if dust is None else sum(dust >= limit for limit in (16, 36, 56, 76))
    air_quality = None if air is None else sum(air > limit for limit in (0, 25, 50, 75))

    humid_raw = _hex(k2.get("s11")) if spec.get("hasHumidFunc") else None
    humidification_enabled = None if humid_raw is None else bool(humid_raw & 0x80)
    water_empty = None if humid_raw is None else humid_raw & 3 == 2
    # Series 4+ devices report actual humidification in the bottom two bits.
    humidifying = None if humid_raw is None or mode is None else not stopped and humid_raw & 3 == 1
    brightness_raw = _hex(k1.get("s15"))
    brightness = None
    if spec.get("hasLighting") or spec.get("hasDisplayBrightness"):
        brightness = {0: "off", 1: "dim", 15: "bright"}.get(
            None if brightness_raw is None else brightness_raw >> 4)
    light_sensor_bright = None
    if spec.get("hasLightSensor") and _hex(k2.get("s7")) is not None:
        light_sensor_bright = k2["s7"] == "FF"
        brightness = "bright" if light_sensor_bright else "dim"
    care_bytes = properties.get("86", "")
    care_raw = _hex(care_bytes[10:12])
    unit_raw = _hex(care_bytes[8:10])
    care_error = None if care_raw is None else bool(care_raw & 4)
    pci_present = k2.get("s9") in ("00", "01")
    pci_output = k2.get("s12") == "FF"
    if mode == 0x20 and k3.get("s8") == "01":
        pci_output = True
    elif mode in (0x40, 0x50, 0x60, 0x30):
        pci_output = True
    plasma_enabled = None if mode is None or care_error is None or _hex(k2.get("s9")) is None or _hex(k2.get("s12")) is None else (
        not stopped and not care_error and pci_present and pci_output)
    return {
        "power": power, "current_mode": current_mode,
        "cloud_enabled": cloud_enabled,
        "temperature": temperature, "temperature_status": temperature_status,
        "humidity": humidity, "humidity_status": humidity_status,
        "pm25": pm25, "pm25_status": pm25_status,
        "odor_level": odor_level, "dust_level": dust_level, "air_quality": air_quality,
        "brightness": brightness, "light_sensor_bright": light_sensor_bright,
        "child_lock": (k3.get("s9") == "FF" if _hex(k3.get("s9")) is not None and
                       (spec.get("hasChildLock") or current_mode in ("cat", "cat_child_lock")) else None),
        "care_error": care_error,
        "unit_date_error": None if unit_raw is None else bool(unit_raw & 4),
        "unit_out_error": None if unit_raw is None else bool(unit_raw & 2),
        "humidification_enabled": humidification_enabled,
        "humidifying": humidifying, "water_empty": water_empty,
        "plasma_enabled": plasma_enabled,
        "maintenance_humid_filter": (k2.get("s10") == "01" if spec.get("hasHumidFunc") and
                                     _hex(k2.get("s10")) is not None else None),
        "maintenance_pci_unit": k2.get("s17") == "FF" if _hex(k2.get("s17")) is not None else None,
        "maintenance_dustbox": (k2.get("s14") == "FF" if spec.get("hasCleaningMecha") and
                                _hex(k2.get("s14")) is not None else None),
        "properties": properties, "last_update": last_update,
    }


def _mode_category(spec: dict) -> int:
    if spec.get("hasCustomDriveMode"):
        return 3
    if not spec.get("hasCloudService") or not spec.get("hasHumidFunc") or spec.get("cannotControlHumid"):
        return 0 if spec.get("hasCloudService") else 1
    return 2


def supported_modes(spec: dict, pets: list | None = None, status: dict | None = None) -> list[str]:
    """Modes visible in the official mode dialog, including registered pets.

    Optional ``model_name`` in spec enables Sharp's model-specific exclusions.
    Pet records use the official ``{'0x00': {'0x02': '0x00'/'0x01'}}`` shape.
    """
    model = spec.get("model_name", "")
    category = _mode_category(spec)
    modes = []
    if not spec.get("nonSpecialMode") and model != "KIM851":
        modes.append("ai_auto")
    if category != 0 or model == "KIM851":
        modes.append("auto")
    if model not in ("KIM851", "FU90KK", "FUM1200") or spec.get("hasDriveModeEco"):
        modes.extend(("pollen", "sleep"))
    if model != "KIM851" and category not in (0, 3):
        modes.append("feel")
    if spec.get("hasSplashParticle"):
        modes.append("splash")
    modes.extend(("quiet", "medium", "strong"))
    if model == "FUM1200":
        modes.extend(("weak", "rapid"))
    if spec.get("hasWeakTurbo"):
        modes.append("turbo")
    if spec.get("hasPetMode") and (status or {}).get("cloud_enabled"):
        types = {pet.get("0x00", {}).get("0x02") for pet in pets or [] if isinstance(pet, dict)}
        if "0x00" in types:
            modes.append("dog")
        if "0x01" in types:
            modes.extend(("cat", "cat_child_lock"))
    return modes


def build_command(action: str, value: Any, status: dict, spec: dict) -> list[dict]:
    """Construct an official request payload; reject unsupported capabilities."""
    current = status.get("current_mode")
    disabled = {"off", "settings", "demo", "humidifier_cleaning",
                "cleaning_stopped", "cleaning", "error"}
    if action == "power" and current in ("settings", "demo", "error"):
        raise ValueError("Power control is disabled in the current device state")
    if action == "mode" and current in disabled:
        raise ValueError("Mode control is disabled in the current device state")
    if action == "humidification" and (
        current in disabled or current == "cleaning_assist" or
        current == "feel" and not spec.get("hasHumidWhileFeel")
    ):
        raise ValueError("Humidification control is disabled in the current device state")
    if action in ("power", "humidification", "cloud") and not isinstance(value, bool):
        raise ValueError(f"{action} requires a boolean")
    if action == "power":
        return [{"epc": "0x80", "edt": "0x30" if value else "0x31"},
                {"opc": "k3", "odt": {"s6": "FF" if value else "00"}}]
    if action == "humidification":
        if not spec.get("hasHumidFunc") or spec.get("cannotControlHumid"):
            raise ValueError("Humidification control is not supported")
        return [{"opc": "k3", "odt": {"s5": "00", "s7": "FF" if value else "00"}}]
    if action == "cloud":
        if not spec.get("hasCloudService"):
            raise ValueError("Cloud service is not supported")
        return [{"opc": "k3", "odt": {"s11": "0008" if value else "0009"}}]
    if action != "mode":
        raise ValueError(f"Unknown control action: {action}")
    if value in ("dog", "cat", "cat_child_lock"):
        if not spec.get("hasPetMode") or not status.get("cloud_enabled"):
            raise ValueError("Pet modes require cloud service")
        return [{"opc": "k3", "odt": {"s11": {"dog": "0001", "cat": "0002", "cat_child_lock": "0003"}[value]}}]
    if value not in supported_modes(spec):
        raise ValueError(f"Unsupported mode: {value}")
    if value == "ai_auto":
        current = status.get("current_mode")
        if current in ("dog", "cat", "cat_child_lock"):
            odt = {"s11": "0004"}
        elif current == "ai_humidity_measurement":
            odt = {"s11": "0005"}
        else:
            odt = {"s1": "20"}
            if status.get("cloud_enabled") and spec.get("hasCustomDriveMode"):
                odt["s2"] = "80"
    else:
        odt = {"s1": MODE_CODES[value], "s5": "00"}
    return [{"opc": "k3", "odt": odt}]
