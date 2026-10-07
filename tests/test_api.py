"""Cloud API transport contracts without a Home Assistant runtime."""
import importlib.util
import json
from pathlib import Path
import unittest

import httpx

spec = importlib.util.spec_from_file_location("cocoro_api_test", Path(__file__).parents[1] / "custom_components/cocoro_air/api.py")
api_module = importlib.util.module_from_spec(spec)
if spec.loader and Path(spec.origin).exists():
    spec.loader.exec_module(api_module)


class ApiTests(unittest.TestCase):
    def make_api(self, handler):
        cls = getattr(api_module, "CocoroAir", None)
        self.assertIsNotNone(cls, "Standalone API client is required")
        api = cls("user@example.com", "secret")
        api._opener = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(api.close)
        return api

    def test_status_preserves_plus_separated_properties(self):
        def handle(request):
            self.assertEqual(request.url.params["epc"], "0x80+0x86")
            self.assertEqual(request.url.params["opc"], "k1+k2+k3")
            self.assertIn(b"%2B", request.url.query)
            return httpx.Response(200, json={"sensor": {"status": 200, "body": {"data": []}}})
        self.assertEqual(self.make_api(handle).get_status("private-device"), {"data": []})

    def test_discovery_preserves_spec_and_unknown_metadata(self):
        device = {"device_id": "d", "device_name": "Room", "model_name": "M", "place": "Upstairs", "spec": {"seriiesCode": 6}, "extra": 42}
        api = self.make_api(lambda r: httpx.Response(200, json={"devices": {"status": 200, "body": {"devices": [device]}}}))
        result = api.query_devices()[0]
        self.assertEqual(result["spec"], device["spec"])
        self.assertEqual(result["extra"], 42)
        self.assertEqual(result["label"], "Room (M) - Upstairs")

    def test_http_and_envelope_401_retry_once(self):
        for envelope in (False, True):
            with self.subTest(envelope=envelope):
                attempts = []
                def handle(request):
                    attempts.append(request)
                    if len(attempts) == 1:
                        return httpx.Response(200, json={"response": {"status": 401}}) if envelope else httpx.Response(401)
                    return httpx.Response(200, json={"response": {"status": 200, "body": {"ok": True}}})
                api = self.make_api(handle)
                logins = []
                api.login = lambda: logins.append(True)
                self.assertEqual(api.get_notifications("d"), {"ok": True})
                self.assertEqual(len(logins), 1)
                self.assertEqual(len(attempts), 2)

    def test_second_401_raises_auth_error(self):
        api = self.make_api(lambda r: httpx.Response(401))
        logins = []
        api.login = lambda: logins.append(True)
        with self.assertRaises(api_module.CocoroAirAuthError):
            api.get_status("d")
        self.assertEqual(len(logins), 1)

    def test_business_error_and_http_error_are_sanitized(self):
        for status, payload, exception in ((200, {"response": {"status": 400, "body": {"private": "secret"}}}, "CocoroAirProtocolError"), (500, {"private": "secret"}, "CocoroAirConnectionError"), (200, {"status": 400, "detail": "secret"}, "CocoroAirProtocolError")):
            with self.subTest(status=status, payload=payload):
                api = self.make_api(lambda r: httpx.Response(status, json=payload))
                with self.assertRaises(getattr(api_module, exception)) as error:
                    api.get_status("private-device")
                self.assertNotIn("secret", str(error.exception))
                self.assertNotIn("private-device", str(error.exception))

    def test_every_envelope_status_is_checked(self):
        api = self.make_api(lambda r: httpx.Response(200, json={"good": {"status": 200, "body": {}}, "bad": {"status": 400, "body": {}}}))
        with self.assertRaises(api_module.CocoroAirProtocolError):
            api.get_status("d")

    def test_json_and_transport_failures(self):
        for kind in ("json", "transport"):
            def handle(request):
                if kind == "transport":
                    raise httpx.ConnectError("secret", request=request)
                return httpx.Response(200, text="secret")
            api = self.make_api(handle)
            error = api_module.CocoroAirConnectionError if kind == "transport" else api_module.CocoroAirProtocolError
            with self.assertRaises(error) as result:
                api.get_status("d")
            self.assertNotIn("secret", str(result.exception))

    def test_control_and_property_endpoint_contracts(self):
        captured = []
        def handle(request):
            captured.append((request.method, request.url.path, dict(request.url.params), json.loads(request.content) if request.content else None))
            return httpx.Response(200, json={"result": {"status": 200, "body": {"ok": True}}})
        api = self.make_api(handle)
        props = [{"apg": "0x01", "code": {"0x00": "0x01"}}]
        commands = [{"epc": "0x80", "edt": "0x30"}]
        cases = [
            (lambda: api.control({"device_id": "d", "model_name": "M", "spec": {"seriiesCode": 6}}, commands), "POST", "sync/air-cleaner", {"deviceToken": "d", "model_name": "M", "additional_request": True, "event_key": "echonet_control", "data": commands}),
            (lambda: api.control_properties("d", props), "POST", "devices/control/air-cleaner", {"deviceToken": "d", "properties": props}),
            (lambda: api.set_notifications("d", {"human": True}), "POST", "notify_setting/air-cleaner", {"bff_device_id": "d", "data": {"human": True}}),
            (lambda: api.get_supplies("d"), "POST", "contents/supplies", {"deviceToken": "d", "properties": [{"apg": "0x02", "apc": ["0x10"]}]}),
            (lambda: api.get_pets("d"), "POST", "contents/pets", {"deviceToken": "d", "properties": [{"apg": "0x01", "apc": ["0x00"]}]}),
            (lambda: api.get_tariff("d"), "POST", "latest/air-cleaner", {"deviceToken": "d", "properties": [{"apg": "0x01", "apc": ["0x50"]}]}),
            (lambda: api.write_supplies("d", props), "POST", "contents/control/supplies", {"deviceToken": "d", "properties": props}),
            (lambda: api.write_pet("d", props), "POST", "contents/control/pets", {"deviceToken": "d", "properties": props}),
            (lambda: api.history("d", props, "start", "end", count=20, offset=5), "POST", "history-conceal/air-cleaner", {"deviceToken": "d", "properties": props, "from_time": "start", "to_time": "end", "count": 20, "offset": 5}),
        ]
        for call, method, path, body in cases:
            self.assertEqual(call(), {"ok": True})
            self.assertEqual(captured[-1], (method, "/v1/cocoro-air/" + path, {}, body))
        api.delete_pet("d", "pet")
        self.assertEqual(captured[-1], ("DELETE", "/v1/cocoro-air/contents/control/pets", {"device_id": "d", "apc": "0x00", "adt": "pet"}, None))


class AdditionalReadTests(unittest.TestCase):
    make_api = ApiTests.make_api
    def test_weather_and_air_history_contracts(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"result": {"status": 200, "body": {"data": []}}})
        api = self.make_api(handle)
        api.get_weather({"zip_code": "1000001"}, "2026-10-07")
        request = requests[-1]
        self.assertEqual(request.url.path, "/v1/cocoro-air/weathers")
        self.assertEqual(dict(request.url.params), {"zipcode": "1000001", "apc": "0x01+0x10+0x20+0x30", "date": "2026-10-07"})
        api.get_air_history("d", "from", "to")
        payload = json.loads(requests[-1].content)
        self.assertEqual(payload["properties"], [{"apg": "0x01", "apc": ["0x20"], "epc_ext": [{"opc": "k1"}, {"opc": "k2"}, {"opc": "k3"}]}])
        self.assertEqual(payload["count"], 1000)

    def test_legacy_sensor_reads_separate_status_rows(self):
        api = self.make_api(lambda r: httpx.Response(200, json={"result": {"status": 200, "body": {"data": [{"k2": {}}, {"k1": {"s1": "19", "s2": "32"}}]}}}))
        self.assertEqual(api.get_sensor_data("d"), {"temperature": 25, "humidity": 50})

    def test_body_business_error_is_rejected(self):
        api = self.make_api(lambda r: httpx.Response(200, json={"result": {"status": 200, "body": {"code": 400}}}))
        with self.assertRaises(api_module.CocoroAirProtocolError):
            api.get_status("d")

    def test_malformed_discovery_is_not_an_empty_device_list(self):
        for body in ({}, {"devices": None}, {"devices": {}}, {"devices": ["invalid"]}):
            api = self.make_api(lambda r: httpx.Response(200, json={"result": {"status": 200, "body": body}}))
            with self.assertRaises(api_module.CocoroAirProtocolError):
                api.query_devices()
        api = self.make_api(lambda r: httpx.Response(200, json={"result": {"status": 200, "body": {"devices": []}}}))
        self.assertEqual(api.query_devices(), [])


if __name__ == "__main__":
    unittest.main()
