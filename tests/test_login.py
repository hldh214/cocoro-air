"""Exercise the real HTTP client against an isolated Auth0 transport."""
import ast
import logging
from pathlib import Path
import re
import unittest
from urllib.parse import parse_qs

import httpx


def load_api():
    import importlib.util
    source = Path(__file__).parents[1] / "custom_components/cocoro_air/api.py"
    spec = importlib.util.spec_from_file_location("cocoro_api_login_tests", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CocoroAir


CocoroAir = load_api()
BASE = "https://cocoroplusapp.jp.sharp"
AUTH = "https://auth.cocoromembers.jp.sharp"


class LoginTests(unittest.TestCase):
    def make_api(self, *, invalid_password=False, missing_state=False, already_logged_in=False, custom_prompt=False):
        self.authenticated = False
        self.login_count = 0

        def respond(request):
            path = request.url.path
            if path == "/v1/cocoro-air/login":
                self.login_count += 1
                return httpx.Response(200, json={"redirectUrl": AUTH + "/authorize"})
            if request.url.host == "auth.cocoromembers.jp.sharp":
                if "text/html" not in request.headers.get("accept", ""):
                    return httpx.Response(406)
                if request.headers.get("user-agent", "").startswith("python-httpx"):
                    return httpx.Response(400)
                if path == "/authorize":
                    target = BASE + "/air" if already_logged_in else AUTH + "/u/login/identifier?state=first"
                    return httpx.Response(302, headers={"Location": target, "Set-Cookie": "session=test; Path=/"})
                if "session=test" not in request.headers.get("cookie", ""):
                    return httpx.Response(400)
                if path.startswith("/u/custom-prompt/"):
                    return httpx.Response(200, text='<h1>Review terms</h1><p>Please confirm the updated terms.</p>'
                                          '<input type="hidden" name="state" value="PRIVATE_TOKEN">'
                                          '<script>PRIVATE_SCRIPT_TOKEN</script><button>Continue</button>')
                if request.method == "GET":
                    state = "first" if path.endswith("identifier") else "second"
                    html = "<form></form>" if missing_state else f'<input name="state" value="{state}">'
                    return httpx.Response(200, text=html)
                form = parse_qs(request.content.decode(), keep_blank_values=True)
                if path.endswith("identifier"):
                    if form.get("state") != ["first"] or form.get("username") != ["user@example.com"]:
                        return httpx.Response(400)
                    return httpx.Response(302, headers={"Location": AUTH + "/u/login/password?state=second"})
                if path.endswith("password"):
                    if invalid_password:
                        return httpx.Response(200, text="Wrong password")
                    if form.get("state") != ["second"] or form.get("password") != ["secret"]:
                        return httpx.Response(400)
                    self.authenticated = True
                    if custom_prompt:
                        return httpx.Response(302, headers={"Location": AUTH + "/u/custom-prompt/terms"})
                    return httpx.Response(302, headers={"Location": BASE + "/air?login=success"})
            if path == "/air":
                self.authenticated = True
                return httpx.Response(200, text="Logged in")
            if path == "/v1/cocoro-air/deviceinfos":
                if not self.authenticated:
                    return httpx.Response(401)
                return httpx.Response(200, json={"device_infos_001": {"body": {"devices": [
                    {"device_id": "device1", "device_name": "Living room", "model_name": "KILS50"}
                ]}}})
            if path == "/v1/cocoro-air/sensors-conceal/air-cleaner":
                if not self.authenticated:
                    return httpx.Response(401)
                return httpx.Response(200, json={"sensors_aircleaner_021": {"body": {"data": [
                    {"k1": {"s1": "19", "s2": "32"}}
                ]}}})
            return httpx.Response(404)

        api = CocoroAir("user@example.com", "secret")
        api._opener = httpx.Client(transport=httpx.MockTransport(respond), headers={
            "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        self.addCleanup(api._opener.close)
        return api

    def test_auth0_login_then_device_discovery(self):
        api = self.make_api()
        api.login()
        self.assertEqual(api.query_devices()[0]["device_id"], "device1")

    def test_existing_session_skips_password_form(self):
        api = self.make_api(already_logged_in=True)
        api.login()
        self.assertEqual(api.get_sensor_data("device1"), {"temperature": 25, "humidity": 50})

    def test_wrong_password_is_rejected(self):
        api = self.make_api(invalid_password=True)
        with self.assertRaisesRegex(Exception, "password"):
            api.login()

    def test_missing_state_is_rejected(self):
        api = self.make_api(missing_state=True)
        with self.assertRaisesRegex(Exception, "state"):
            api.login()

    def test_sensor_401_reauthenticates(self):
        api = self.make_api()
        self.assertEqual(api.get_sensor_data("device1"), {"temperature": 25, "humidity": 50})
        self.assertEqual(self.login_count, 1)

    def test_device_discovery_401_reauthenticates(self):
        api = self.make_api()
        self.assertEqual(api.query_devices()[0]["device_id"], "device1")
        self.assertEqual(self.login_count, 1)

    def test_custom_prompt_requires_manual_account_confirmation(self):
        api = self.make_api(custom_prompt=True)
        with self.assertRaisesRegex(Exception, "https://cocoroplusapp.jp.sharp/air") as result:
            api.login()
        self.assertNotIn("PRIVATE", str(result.exception))


if __name__ == "__main__":
    unittest.main()
