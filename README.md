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

1. Go to https://cocoroplusapp.jp.sharp/air and sign in/up
2. Get `device_id` from devtools
3. Get Cookie for https://cocoromembers.jp.sharp/ from devtools

```yaml
cocoro_air:
  email: YOUR_EMAIL
  password: YOUR_PASSWORD
  device_id: YOUR_DEVICE_ID
```
