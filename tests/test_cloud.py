"""Protocol encoders reject invalid controls and preserve cloud metadata."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).parents[1] / 'custom_components/cocoro_air/cloud.py'
spec = importlib.util.spec_from_file_location('cloud', path)
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)


class CloudTests(unittest.TestCase):
    def test_tariff_round_trip_preserves_opaque_metadata(self):
        record = {'0x50': [{'0x00': 'old', '0x10': '0x00000000', '0x11': ['0x00008CA0'] * 24}]}
        self.assertEqual(cloud.decode_tariff(record), [36.0] * 24)
        payload = cloud.tariff_payload([31.123] * 24, record)
        self.assertEqual(payload[0]['code']['0x50']['0x10'], '0x00000000')
        self.assertEqual(payload[0]['code']['0x50']['0x11'][0], '0x00007993')
        for values in [[31] * 23, [float('nan')] * 24, [-1] * 24, [100] * 24]:
            with self.assertRaises(ValueError):
                cloud.tariff_payload(values, record)

    def test_notification_partial_merge_keeps_unrelated_flags(self):
        original = {'air_cleaner': True, 'temperature': False, 'temperature_detail': {'temperature_lower': 10, 'temperature_upper': 30}}
        result = cloud.notification_payload('private', original, {'temperature': True, 'temperature_upper': 32})
        self.assertTrue(result['data']['air_cleaner'])
        self.assertEqual(result['data']['temperature_detail'], {'temperature_lower': 10, 'temperature_upper': 32})
        self.assertEqual(original['temperature_detail']['temperature_upper'], 30)
        for patch in [{'temperature': 'false'}, {'temperature_upper': 41}, {'temperature_lower': 33}, {'unexpected': True}]:
            with self.assertRaises(ValueError):
                cloud.notification_payload('private', original, patch)

    def test_pet_update_keeps_identifier_and_cat_age_validation(self):
        payload = cloud.pet_payload({'name': 'Mimi', 'species': 'cat', 'sex': 'female', 'age': 'senior'}, pet_id='existing')
        pet = payload[0]['code']['0x00']
        self.assertEqual(pet['0x00'], 'existing')
        self.assertEqual((pet['0x02'], pet['0x04'], pet['0x05']), ('0x01', '0x01', '0x02'))
        with self.assertRaises(ValueError):
            cloud.pet_payload({'name': '', 'species': 'dog'})
        with self.assertRaises(ValueError):
            cloud.pet_payload({'name': 'Mimi', 'species': 'cat', 'age': 'adult'})

    def test_supplies_uses_spec_life_and_hex_multiplier(self):
        record = {'0x10': [{'0x00': '0x00', '0x01': 'filter', '0x02': '0x0014'}, {'0x00': '0x40', '0x11': '0x000002D0', '0x20': '0x00000064', '0x21': '2026-01-01'}]}
        result = cloud.parse_supplies(record, {'dustFilterUsed': 200, 'totalOperatingTime': 44000}, {'dustFilterLimit': 1000})
        self.assertEqual(result['dust_filter']['remaining'], 40)
        self.assertTrue(result['back_panel']['needs_cleaning'])
        self.assertEqual(result['back_panel']['last_cleaned'], '2026-01-01')
        self.assertIsNone(cloud.parse_supplies(record, {}, {})['dust_filter']['remaining'])
        record['0x10'][0]['0x02'] = 'invalid'
        self.assertIsNone(cloud.parse_supplies(record, {'dustFilterUsed': 10}, {'dustFilterLimit': 1000})['dust_filter']['remaining'])

    def test_supplies_decodes_raw_k1_and_both_pci_counters(self):
        record = {'0x10': [{'0x00': '0x11', '0x02': '0x000A'}]}
        status = {'k1': {'s4': '0064', 's5': '0258'}}
        result = cloud.parse_supplies(record, status, {'pciUnitLimit': 1000, 'hasPciTwiceUnit': True})
        self.assertEqual(result['pci_unit']['remaining'], 40)

    def test_supply_replacement_and_physical_reset_limits(self):
        self.assertEqual(cloud.supplies_action_commands('dust_filter', 'replace'), [{'opc': 'k3', 'odt': {'s4': '08'}}])
        self.assertEqual(cloud.supplies_action_commands('humidifying_filter', 'replace', model='KIM851'), [{'opc': 'k3', 'odt': {'s4': '12'}}])
        self.assertEqual(cloud.supplies_action_commands('humidifying_filter', 'clean', model='KIM851'), [{'opc': 'k3', 'odt': {'s4': '10'}}])
        self.assertEqual(cloud.supplies_action_commands('humidifying_filter', 'clean'), [])
        self.assertEqual(cloud.supplies_action_commands('pci_unit', 'replace'), [])
        with self.assertRaises(ValueError):
            cloud.supplies_action_commands('unknown', 'replace')

    def test_cleaning_state_accepts_properties_wrapper_and_error_flag(self):
        record = {'0x10': [{'0x00': '0x11', '0x11': '0x10', '0x20': '0x00'}]}
        raw = {'properties': {'k1': {'s4': '0064', 's3': '1000'}, '0x86': '000000000004'}}
        result = cloud.parse_supplies(record, raw, {'pciUnitLimit': 1000})
        self.assertTrue(result['pci_unit']['needs_cleaning'])

    def test_cost_records_decode_hex_without_losing_dates(self):
        self.assertEqual(cloud.decode_cost_records({'data': [{'time': '2026-10-01T00:00:00+00:00', '0x40': {'0x00': '0x00000534'}}]}), [{'time': '2026-10-01T00:00:00+00:00', 'cost': 1.332}])

    def test_notification_clear_and_null_detail(self):
        current = {'temperature': True, 'temperature_detail': {'temperature_lower': 10, 'temperature_upper': 30}}
        cleared = cloud.notification_payload('device', current, {'temperature_lower': None})
        self.assertEqual(cleared['data']['temperature_detail'], {'temperature_upper': 30})
        self.assertEqual(cloud.notification_payload('device', {'temperature_detail': None}, {'temperature_upper': 25})['data']['temperature_detail'], {'temperature_upper': 25})
        with self.assertRaises(ValueError):
            cloud.notification_payload('device', {}, {'mode': True})

    def test_supplies_malformed_counter_is_unavailable(self):
        record = {'0x10': [{'0x00': '0x00', '0x02': '0x000A'}, {'0x00': '0x40', '0x11': 'bad', '0x20': None}]}
        parsed = cloud.parse_supplies(record, {'k1': {'s8': 'unavailable', 's3': None}, '0x86': 'not-a-hex-error'}, {'dustFilterLimit': 1000})
        self.assertIsNone(parsed['dust_filter']['remaining'])
        self.assertIsNone(parsed['back_panel']['needs_cleaning'])
        self.assertIsNone(cloud.parse_supplies(record, {}, {})['dust_filter']['remaining'])
        record['0x10'][0]['0x02'] = 'invalid'
        self.assertIsNone(cloud.parse_supplies(record, {'dustFilterUsed': 10}, {'dustFilterLimit': 1000})['dust_filter']['remaining'])

    def test_weather_current_three_hour_slot_and_daily_indices(self):
        record = {'0x30': [{'0x03': str(20 + h), '0x05': '58', '0x02': '200'} for h in range(8)], '0x20': [{'0x05': '1', '0x06': '3', '0x07': '2', '0x08': '80'}]}
        parsed = cloud.parse_weather({'data': [record]}, 10)
        self.assertEqual(parsed, {'outdoor_temperature': 23.0, 'outdoor_humidity': 58.0, 'weather_code': '200', 'pollen': 1, 'pm25_forecast': 0, 'yellow_sand': 1, 'laundry': 3})
        self.assertIsNone(cloud.parse_weather({'data': []}, 10)['outdoor_temperature'])

    def test_supplies_reset_only_records_cloud_care(self):
        result = cloud.supplies_reset_payload('back_panel', '2026-10-07T12:00:00+09:00')
        self.assertEqual(result, [{'apg': '0x02', 'code': {'0x10': {'0x00': '0x40', '0x21': '2026-10-07T12:00:00+09:00', '0x30': '0x00'}}}])
        with self.assertRaises(ValueError):
            cloud.supplies_reset_payload('unknown', '2026-01-01')
