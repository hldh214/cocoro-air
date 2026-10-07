# cocoro-air

https://cocoroplusapp.jp.sharp/air

## Supported features

- [ ] Air Cleaner
    - [x] Temperature Sensor
    - [x] Humidity Sensor
    - [ ] Air Quality Sensor
    - [ ] Filter Remaining Sensor
    - [ ] Power
    - [ ] Mode
    - [ ] Fan Speed

## Installation

### Install via HACS Custom repositories

https://hacs.xyz/docs/faq/custom_repositories

## Configuration

1. Ensure you have an account at [Cocoro Air](https://cocoroplusapp.jp.sharp/air).
2. Go to **Settings** -> **Devices & Services** in Home Assistant.
3. Click the **Add Integration** button.
4. Search for **Cocoro Air**.
5. Follow the on-screen instructions to enter your Email and Password, then select your device.

## Auth0 login compatibility (1.1.0)

Adapts the [Auth0 login fix from yuyuvn/cocoro-air](https://github.com/yuyuvn/cocoro-air/commit/67e734eea9c9c0987c599a102d67c0a4e2c13ddb)
to this integration's existing multi-device configuration. Login pages use
browser HTML headers to avoid HTTP 406. Existing device selections and
temperature/humidity entity IDs remain unchanged. Expired sessions are
renewed once when device discovery or sensor requests return HTTP 401.

After installing the update, restart Home Assistant to load the new Python code.

Run the isolated login regression tests (requires `httpx`):

```sh
python -m unittest discover -s tests -v
```
