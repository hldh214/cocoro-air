"""Synchronous, serialized Cocoro Air cloud client with no HA dependencies."""
import logging
import re
from threading import RLock

import httpx

_LOGGER = logging.getLogger(__name__)
BASE_URL = "https://cocoroplusapp.jp.sharp/v1/cocoro-air"


class CocoroAirError(Exception):
    """Base sanitized cloud error."""


class CocoroAirAuthError(CocoroAirError):
    """Authentication or account confirmation failed."""


class CocoroAirConnectionError(CocoroAirError):
    """The cloud service could not be reached."""


class CocoroAirProtocolError(CocoroAirError):
    """The service returned an invalid response or rejected a request."""


class CocoroAir:
    def __init__(self, email, password):
        self._opener = None
        self._lock = RLock()
        self.email = email
        self.password = password

    @property
    def opener(self):
        with self._lock:
            if self._opener is None:
                self._opener = httpx.Client(headers={
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
                    'Accept': 'application/json'
                }, timeout=10)
            return self._opener

    def close(self):
        with self._lock:
            if self._opener is not None:
                self._opener.close()
                self._opener = None

    @staticmethod
    def _login_state(response):
        match = re.search(r'name="state" value="([^"]+)"', response.text)
        if match is None:
            raise ValueError("Login page is missing the state field")
        return match.group(1)

    def login(self):
        with self._lock:
            try:
                return self._login()
            except httpx.RequestError:
                raise CocoroAirConnectionError("Unable to reach the login service") from None
            except httpx.HTTPStatusError:
                raise CocoroAirAuthError("Login service rejected authentication") from None
            except (KeyError, TypeError):
                raise CocoroAirAuthError("Invalid login service response") from None
            except ValueError as error:
                # Only our own fixed messages may cross the API boundary.
                if "Additional account confirmation required" in str(error):
                    raise CocoroAirAuthError(
                        "Additional account confirmation required. Sign in at "
                        "https://cocoroplusapp.jp.sharp/air, complete any account prompts "
                        "(such as updated terms), then reload the Cocoro Air integration."
                    ) from None
                if "state field" in str(error):
                    raise CocoroAirAuthError("Login page is missing the state field") from None
                raise CocoroAirAuthError("Login failed during identifier or password authentication") from None

    def _login(self):
        """Authenticate using Cocoro Members' identifier-first Auth0 flow.

        Adapted from yuyuvn/cocoro-air commit 67e734e. Login pages require
        an HTML Accept header; the API client's JSON default returns 406.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        res = self.opener.get('https://cocoroplusapp.jp.sharp/v1/cocoro-air/login')
        res.raise_for_status()
        res = self.opener.get(res.json()['redirectUrl'], headers=headers, follow_redirects=True)
        res.raise_for_status()
        if res.url.host == 'cocoroplusapp.jp.sharp' and res.url.path.startswith('/air'):
            _LOGGER.info('Login success (existing session)')
            return
        if res.url.host != 'auth.cocoromembers.jp.sharp' or res.url.path != '/u/login/identifier':
            raise ValueError("Unexpected login page")

        state = self._login_state(res)
        res = self.opener.post(
            'https://auth.cocoromembers.jp.sharp/u/login/identifier',
            params={'state': state},
            data={
                'state': state,
                'username': self.email,
                'captcha': '',
                'js-available': 'true',
                'webauthn-available': 'false',
                'is-brave': 'false',
                'webauthn-platform-available': 'false',
                'action': 'default',
            },
            headers=headers,
            follow_redirects=True,
        )
        res.raise_for_status()
        if res.url.host != 'auth.cocoromembers.jp.sharp' or res.url.path != '/u/login/password':
            raise ValueError("Unexpected page after identifier step")

        state = self._login_state(res)
        res = self.opener.post(
            'https://auth.cocoromembers.jp.sharp/u/login/password',
            params={'state': state},
            data={'state': state, 'username': self.email,
                  'password': self.password, 'action': 'default'},
            headers=headers,
            follow_redirects=True,
        )
        res.raise_for_status()
        if res.url.host == 'auth.cocoromembers.jp.sharp' and res.url.path.startswith('/u/custom-prompt/'):
            raise ValueError(
                "Additional account confirmation required. Sign in at "
                "https://cocoroplusapp.jp.sharp/air, complete any account prompts "
                "(such as updated terms), then reload the Cocoro Air integration."
            )
        if (res.url.host != 'cocoroplusapp.jp.sharp'
                or not res.url.path.startswith('/air')
                or b'login=success' not in res.url.query):
            raise ValueError(
                "Login failed after password step "
                f"(HTTP {res.status_code}, {res.url.host}{res.url.path})"
            )
        _LOGGER.info('Login success')

    @staticmethod
    def _response_statuses(data):
        """Inspect every envelope, including top-level problem responses."""
        envelopes = [data] + [value for value in data.values() if isinstance(value, dict)]
        statuses = []
        for envelope in envelopes:
            if "status" in envelope:
                try:
                    statuses.append(int(envelope["status"]))
                except (ValueError, TypeError):
                    raise CocoroAirProtocolError("Invalid cloud response status") from None
            body = envelope.get("body")
            if isinstance(body, dict) and "code" in body:
                try:
                    code = int(body["code"])
                except (ValueError, TypeError):
                    raise CocoroAirProtocolError("Invalid cloud business response code") from None
                if code != 0:
                    statuses.append(code)
        return statuses

    def _request(self, method, path, **kwargs):
        with self._lock:
            for attempt in range(2):
                try:
                    response = self.opener.request(method, BASE_URL + '/' + path.lstrip('/'), **kwargs)
                except httpx.RequestError:
                    raise CocoroAirConnectionError("Unable to reach Cocoro Air") from None
                if response.status_code == 401:
                    if attempt:
                        raise CocoroAirAuthError("Cloud session is unauthorized")
                    self.login()
                    continue
                if response.status_code >= 500:
                    raise CocoroAirConnectionError("Cocoro Air service is unavailable")
                if not response.is_success:
                    raise CocoroAirProtocolError("Cloud request was rejected")
                try:
                    data = response.json()
                except ValueError:
                    raise CocoroAirProtocolError("Cloud response is not valid JSON") from None
                if not isinstance(data, dict):
                    raise CocoroAirProtocolError("Invalid cloud response envelope")
                statuses = self._response_statuses(data)
                if 401 in statuses:
                    if attempt:
                        raise CocoroAirAuthError("Cloud session is unauthorized")
                    self.login()
                    continue
                if any(status < 200 or status >= 300 for status in statuses):
                    rejected = sorted({status for status in statuses if status < 200 or status >= 300})
                    raise CocoroAirProtocolError(f"Cloud request was rejected (status {','.join(map(str, rejected))})")
                return data
        raise CocoroAirAuthError("Cloud session is unauthorized")

    def request(self, method, path, **kwargs):
        envelope = self._request(method, path, **kwargs)
        bodies = [value["body"] for value in envelope.values()
                  if isinstance(value, dict) and "body" in value]
        if "body" in envelope:
            bodies.insert(0, envelope["body"])
        if not bodies or not isinstance(bodies[0], dict):
            raise CocoroAirProtocolError("Cloud response is missing a body")
        return bodies[0]

    def query_devices(self):
        envelope = self._request("GET", "deviceinfos")
        devices = []
        found = False
        for value in envelope.values():
            if not isinstance(value, dict) or not isinstance(value.get("body"), dict):
                continue
            if "devices" not in value["body"]:
                continue
            found = True
            if not isinstance(value["body"]["devices"], list):
                raise CocoroAirProtocolError("Invalid device discovery response")
            for device in value["body"]["devices"]:
                if not isinstance(device, dict) or not device.get("device_id"):
                    raise CocoroAirProtocolError("Invalid device discovery response")
                result = dict(device)
                name = device.get("device_name") or device["device_id"]
                model = device.get("model_name", "")
                place = device.get("place", "")
                result["label"] = str(name) + (f" ({model})" if model else "") + (f" - {place}" if place else "")
                result.setdefault("spec", {})
                devices.append(result)
        if not found:
            raise CocoroAirProtocolError("Device discovery response is missing devices")
        return devices

    def get_status(self, device_id):
        return self.request("GET", "sensors-conceal/air-cleaner", params={
            "device_id": device_id, "event_key": "echonet_property",
            "epc": "0x80+0x86", "opc": "k1+k2+k3",
        })

    def get_sensor_data(self, device_id):
        if not device_id:
            return None
        body = self.get_status(device_id)
        try:
            values = {}
            for row in body["data"]:
                if isinstance(row, dict) and isinstance(row.get("k1"), dict):
                    values.update(row["k1"])
            return {"temperature": int(values["s1"], 16), "humidity": int(values["s2"], 16)}
        except (KeyError, IndexError, ValueError, TypeError):
            return None

    def get_notifications(self, device_id):
        return self.request("GET", "notify_setting/air-cleaner", params={"device_id": device_id})

    def set_notifications(self, device_id, data):
        return self.request("POST", "notify_setting/air-cleaner", json={"bff_device_id": device_id, "data": data})

    def read_properties(self, device_id, path, properties):
        return self.request("POST", path, json={"deviceToken": device_id, "properties": properties})

    def control(self, device, commands):
        try:
            additional_request = int(device.get("spec", {}).get("seriiesCode", 0)) >= 6
        except (TypeError, ValueError):
            additional_request = False
        return self.request("POST", "sync/air-cleaner", json={
            "deviceToken": device["device_id"], "model_name": device.get("model_name", ""),
            "additional_request": additional_request, "event_key": "echonet_control", "data": commands,
        })

    def control_properties(self, device_id, properties):
        return self.read_properties(device_id, "devices/control/air-cleaner", properties)

    def get_supplies(self, device_id):
        return self.read_properties(device_id, "contents/supplies", [{"apg": "0x02", "apc": ["0x10"]}])

    def get_pets(self, device_id):
        return self.read_properties(device_id, "contents/pets", [{"apg": "0x01", "apc": ["0x00"]}])

    def get_tariff(self, device_id):
        return self.read_properties(device_id, "latest/air-cleaner", [{"apg": "0x01", "apc": ["0x50"]}])

    def get_weather(self, device, date=None):
        params = {"zipcode": device["zip_code"], "apc": "0x01+0x10+0x20+0x30"}
        if date is not None:
            params["date"] = date
        return self.request("GET", "weathers", params=params)

    def get_air_history(self, device_id, from_time, to_time, count=1000):
        return self.history(device_id, [{
            "apg": "0x01", "apc": ["0x20"],
            "epc_ext": [{"opc": "k1"}, {"opc": "k2"}, {"opc": "k3"}],
        }], from_time, to_time, count=count)

    def history(self, device_id, properties, from_time, to_time, count=100, offset=0):
        return self.request("POST", "history-conceal/air-cleaner", json={
            "deviceToken": device_id, "properties": properties,
            "from_time": from_time, "to_time": to_time, "count": count, "offset": offset,
        })

    def write_supplies(self, device_id, properties):
        return self.read_properties(device_id, "contents/control/supplies", properties)

    def write_pet(self, device_id, properties):
        return self.read_properties(device_id, "contents/control/pets", properties)

    def delete_pet(self, device_id, pet_id):
        return self.request("DELETE", "contents/control/pets", params={"device_id": device_id, "apc": "0x00", "adt": pet_id})
