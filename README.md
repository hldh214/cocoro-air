# cocoro-air

https://cocoroplusapp.jp.sharp/air

## Supported features

- [ ] Air Cleaner
    - [x] Temperature Sensor
    - [x] Humidity Sensor
    - [x] Humidifier Mode
    - [ ] Filter Remaining Sensor
    - [ ] ~Power~
    - [ ] ~Fan Speed~
    - [ ] ~Air Quality Sensor~

Note: You can use [echonetlite](https://github.com/scottyphillips/echonetlite_homeassistant) for Power, Air quality and Fan speed control. Thus this plugin won't support it unless someone contribute to the project.

## Installation

### Install via HACS Custom repositories

https://hacs.xyz/docs/faq/custom_repositories

## Configuration

1. Ensure you have an account at [Cocoro Air](https://cocoroplusapp.jp.sharp/air).
2. Get `device_id` and model name from browser devtools (e.g. from the Cocoro Air app).
3. Go to **Settings** → **Devices & Services** in Home Assistant, click **Add Integration**, and search for **Cocoro Air**.
4. Enter your email, password, device_id and model name.

## Model supported

Model that has been tested:
- KILS50
