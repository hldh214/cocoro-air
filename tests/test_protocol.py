"""Protocol contracts taken from Sharp's official control application."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).parents[1] / "custom_components/cocoro_air/protocol.py"
loader = importlib.util.spec_from_file_location("cocoro_protocol", SOURCE)
protocol = importlib.util.module_from_spec(loader)
loader.loader.exec_module(protocol)

SPEC = {"seriiesCode": 6, "hasCloudService": True, "hasHumidFunc": True,
        "hasHumidWhileFeel": True, "hasDustSensor": True, "hasPM25Sensor": True,
        "hasPetMode": True, "hasSplashParticle": True, "hasLightSensor": True}


def sample(mode="20", **sections):
    """Synthetic device measurements, in the official multiple-row format."""
    props = {"0x80": "0x30", "0x86": "0x080000050000000000000000",
             "k1": {"s1": "1a", "s2": "2b", "s7": "000c", "s15": "f0"},
             "k2": {"s1": "11", "s2": "24", "s4": "33", "s5": "02",
                    "s8": "00", "s9": "00", "s10": "00", "s11": "81",
                    "s12": "ff", "s14": "00", "s17": "00"},
             "k3": {"s1": mode, "s2": "80", "s10": "00", "s8": "00"}}
    for section, values in sections.items():
        if isinstance(values, dict):
            props[section].update(values)
        else:
            props[section] = values
    return {"data": [{key: value, "time": "2026-01-01T00:00:00Z"}
                     for key, value in props.items()]}


class ProtocolTests(unittest.TestCase):
    def test_malformed_property_responses_raise_safe_value_errors(self):
        for body in (None, [], {"data": None}, {"data": {}}, {"data": "PRIVATE"},
                     {"data": [None]}, {"data": [{"k1": None}]},
                     {"data": [{"k2": "PRIVATE"}]}, {"data": [{"k3": []}]},
                     {"data": [{"0x86": []}]}):
            with self.assertRaises(ValueError) as error:
                protocol.parse_status(body, SPEC)
            self.assertNotIn("PRIVATE", str(error.exception))

    def test_missing_boolean_properties_remain_unknown(self):
        for body in ({"data": []}, {"data": [{"k3": {"s1": "20"}}]}):
            result = protocol.parse_status(body, dict(SPEC, hasCleaningMecha=True, hasChildLock=True))
            for key in ("power", "cloud_enabled", "humidification_enabled", "humidifying",
                        "water_empty", "plasma_enabled", "child_lock", "care_error",
                        "unit_date_error", "unit_out_error", "maintenance_humid_filter",
                        "maintenance_pci_unit", "maintenance_dustbox", "light_sensor_bright"):
                self.assertIsNone(result[key], key)
        result = protocol.parse_status({"data": [{"k3": {"s1": "20", "s2": None}}]}, SPEC)
        self.assertIsNone(result["cloud_enabled"])

    def test_merges_rows_and_decodes_measurements(self):
        result = protocol.parse_status(sample(), SPEC)
        self.assertEqual((result["temperature"], result["humidity"], result["pm25"]), (26, 43, 12))
        self.assertEqual((result["odor_level"], result["dust_level"], result["air_quality"]), (1, 2, 3))
        self.assertTrue(result["cloud_enabled"])
        self.assertTrue(result["power"])
        self.assertTrue(result["humidification_enabled"])
        self.assertTrue(result["humidifying"])
        self.assertTrue(result["plasma_enabled"])
        self.assertEqual(result["current_mode"], "ai_auto")
        self.assertEqual(result["properties"]["80"], "30")
        self.assertNotIn("time", result["properties"])

    def test_power_off_hides_retained_measurements(self):
        result = protocol.parse_status(sample(mode="00", **{"0x80": "0x31"}), SPEC)
        for key in ("temperature", "humidity", "pm25", "odor_level", "dust_level", "air_quality"):
            self.assertIsNone(result[key], key)
        self.assertFalse(result["power"])
        self.assertFalse(result["plasma_enabled"])
        self.assertEqual(result["current_mode"], "off")

    def test_sentinels_are_not_numeric_measurements(self):
        cases = [("80", "18", "8000", "low", "low", "measuring"),
                 ("33", "4c", "01f4", "high", "high", "high"),
                 ("1a", "2b", "0000", "normal", "normal", "low")]
        for temp, humidity, pm, ts, hs, ps in cases:
            result = protocol.parse_status(sample(k1={"s1": temp, "s2": humidity, "s7": pm}), SPEC)
            self.assertEqual((result["temperature_status"], result["humidity_status"], result["pm25_status"]), (ts, hs, ps))
            for key, state in (("temperature", ts), ("humidity", hs), ("pm25", ps)):
                if state != "normal":
                    self.assertIsNone(result[key])

    def test_capabilities_and_unknown_data(self):
        result = protocol.parse_status(sample(), {"seriiesCode": 6})
        for key in ("pm25", "dust_level", "humidification_enabled", "water_empty", "brightness"):
            self.assertIsNone(result[key])
        self.assertEqual(result["pm25_status"], "unsupported")
        result = protocol.parse_status({"data": [{"k3": {"s1": "20"}}]}, SPEC)
        self.assertIsNone(result["temperature"])
        self.assertIsNone(result["humidity"])

    def test_humidification_and_maintenance(self):
        result = protocol.parse_status(sample(k2={"s11": "82", "s10": "01", "s17": "ff"}), SPEC)
        self.assertTrue(result["water_empty"])
        self.assertFalse(result["humidifying"])
        self.assertTrue(result["maintenance_humid_filter"])
        self.assertTrue(result["maintenance_pci_unit"])
        self.assertFalse(result["maintenance_dustbox"])

    def test_supported_modes_and_dynamic_pets(self):
        basic = ["ai_auto", "auto", "pollen", "sleep", "feel", "splash", "quiet", "medium", "strong"]
        self.assertEqual(protocol.supported_modes(SPEC), basic)
        pets = [{"0x00": {"0x02": "0x00"}}, {"0x00": {"0x02": "0x01"}}]
        self.assertEqual(protocol.supported_modes(SPEC, pets, {"cloud_enabled": True}), basic + ["dog", "cat", "cat_child_lock"])
        self.assertEqual(protocol.supported_modes(SPEC, pets, {"cloud_enabled": False}), basic)

    def test_partial_property_rows_merge_without_retaining_identifiers(self):
        body = sample()
        body["data"].extend([
            {"k1": {"s1": "1b"}, "deviceToken": "must-not-leak", "time": "2026-01-02T00:00:00Z"},
            {"device_id": "must-not-leak", "k3": {"s1": "20", "s10": "82"}},
        ])
        result = protocol.parse_status(body, SPEC)
        self.assertEqual(result["temperature"], 27)
        self.assertEqual(result["humidity"], 43)
        self.assertEqual(result["current_mode"], "dog")
        self.assertNotIn("must-not-leak", str(result))
        self.assertEqual(result["last_update"], "2026-01-02T00:00:00Z")

    def test_legacy_humidity_bounds_and_brightness_capability(self):
        spec = dict(SPEC, seriiesCode=5, hasDisplayBrightness=True)
        result = protocol.parse_status(sample(k1={"s2": "19", "s15": "10"}), spec)
        self.assertEqual(result["humidity"], 25)
        self.assertEqual(result["brightness"], "dim")
        result = protocol.parse_status(sample(k1={"s2": "64"}), spec)
        self.assertEqual(result["humidity_status"], "high")
        self.assertIsNone(result["humidity"])

    def test_plasma_maintenance_error_and_mechanical_cleaning(self):
        result = protocol.parse_status(sample(**{"0x86": "0x080000050004000000000000"}), SPEC)
        self.assertFalse(result["plasma_enabled"])
        result = protocol.parse_status(sample(mode="1e", **{"0x80": "0x31"}), SPEC)
        self.assertTrue(result["power"])
        self.assertEqual(result["current_mode"], "cleaning")
        self.assertIsNone(result["temperature"])

    def test_ambient_light_sensor_and_faults(self):
        result = protocol.parse_status(sample(k2={"s7": "ff"}, k3={"s9": "ff"},
            **{"0x86": "0x080000050006000000000000"}), dict(SPEC, hasChildLock=True))
        self.assertTrue(result["light_sensor_bright"])
        self.assertEqual(result["brightness"], "bright")
        self.assertTrue(result["care_error"])
        self.assertTrue(result["child_lock"])
        result = protocol.parse_status(sample(k2={"s7": "00"}), SPEC)
        self.assertEqual(result["brightness"], "dim")
        self.assertFalse(result["light_sensor_bright"])
        self.assertIsNone(result["child_lock"])

    def test_mode_value_type_is_validated(self):
        for value in (None, [], {}, 1):
            with self.assertRaises(ValueError):
                protocol.build_command("mode", value, {}, SPEC)

    def test_official_command_payloads(self):
        status = protocol.parse_status(sample(), SPEC)
        self.assertEqual(protocol.build_command("power", True, status, SPEC), [
            {"epc": "0x80", "edt": "0x30"}, {"opc": "k3", "odt": {"s6": "FF"}}])
        self.assertEqual(protocol.build_command("mode", "sleep", status, SPEC),
                         [{"opc": "k3", "odt": {"s1": "11", "s5": "00"}}])
        self.assertEqual(protocol.build_command("humidification", False, status, SPEC),
                         [{"opc": "k3", "odt": {"s5": "00", "s7": "00"}}])
        self.assertEqual(protocol.build_command("cloud", True, status, SPEC),
                         [{"opc": "k3", "odt": {"s11": "0008"}}])

    def test_disabled_controls_match_official_webpage(self):
        for mode in ("settings", "demo", "error"):
            with self.assertRaises(ValueError):
                protocol.build_command("power", True, {"current_mode": mode}, SPEC)
        forbidden_modes = ("off", "settings", "demo", "humidifier_cleaning",
                           "cleaning_stopped", "cleaning", "error")
        for mode in forbidden_modes:
            for action, value in (("mode", "auto"), ("humidification", True)):
                with self.assertRaises(ValueError, msg=f"{action}: {mode}"):
                    protocol.build_command(action, value, {"current_mode": mode}, SPEC)
        with self.assertRaises(ValueError):
            protocol.build_command("humidification", True, {"current_mode": "cleaning_assist"}, SPEC)
        with self.assertRaises(ValueError):
            protocol.build_command("humidification", True, {"current_mode": "feel"},
                                   dict(SPEC, hasHumidWhileFeel=False))
        self.assertEqual(protocol.build_command("power", True, {"current_mode": "off"}, SPEC)[0]["edt"], "0x30")

    def test_cat_child_lock_is_a_separate_official_choice(self):
        status = {"current_mode": "ai_auto", "cloud_enabled": True}
        self.assertEqual(protocol.build_command("mode", "cat_child_lock", status, SPEC),
                         [{"opc": "k3", "odt": {"s11": "0003"}}])
        self.assertEqual(protocol.build_command("mode", "cat", status, SPEC),
                         [{"opc": "k3", "odt": {"s11": "0002"}}])
        parsed = protocol.parse_status(sample(k3={"s10": "84", "s9": "ff"}), SPEC)
        self.assertEqual(parsed["current_mode"], "cat_child_lock")
        self.assertTrue(parsed["child_lock"])
        self.assertEqual(protocol.build_command("mode", "ai_auto", parsed, SPEC),
                         [{"opc": "k3", "odt": {"s11": "0004"}}])

    def test_ai_exit_commands_and_invalid_requests(self):
        self.assertEqual(protocol.build_command("mode", "ai_auto", {"current_mode": "dog"}, SPEC),
                         [{"opc": "k3", "odt": {"s11": "0004"}}])
        self.assertEqual(protocol.build_command("mode", "ai_auto", {"current_mode": "ai_humidity_measurement"}, SPEC),
                         [{"opc": "k3", "odt": {"s11": "0005"}}])
        for action, value, spec in [("mode", "turbo", SPEC), ("cloud", True, {}),
                                    ("humidification", True, {}), ("power", "false", SPEC),
                                    ("unknown", True, SPEC)]:
            with self.assertRaises(ValueError):
                protocol.build_command(action, value, {}, spec)


if __name__ == "__main__":
    unittest.main()
