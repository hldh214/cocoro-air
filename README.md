# cocoro-air

Home Assistant integration for [Sharp COCORO AIR](https://cocoroplusapp.jp.sharp/air).

Version 1.2.0 brings the authenticated KI-PX70 webpage's device controls and cloud settings into Home Assistant. The implementation was investigated using an authorized real account, its device capabilities, the live webpage and the official frontend's request builders. Features are selected by device capabilities; other models have not received the same live verification.

## Features

| Webpage feature | Home Assistant |
| --- | --- |
| Power and operating mode | Fan with exact Sharp presets: AI auto, auto, pollen, sleep, feel, splash, quiet, medium and strong, where supported |
| Humidification | Switch, humidifying and water-empty binary sensors |
| Cloud home fit | Switch |
| Temperature, humidity, air cleanliness, odor, dust, PM2.5 and ambient brightness | Sensors; stopped/invalid measurements become unknown, matching the webpage |
| Plasmacluster, care and unit faults, child lock | Binary sensors where applicable |
| Consumable remaining life, maintenance dates and care alerts | Diagnostic sensors and binary sensors |
| Cleaning/replacement completion and disposable prefilter use | `maintain_supply` and `set_prefilter` actions |
| Air-cleaner and temperature notifications | Switches and lower/upper threshold numbers; `set_notifications` can also clear thresholds |
| Pet registration, editing and removal | `set_pet`, `delete_pet` and `get_cloud_info`; eligible pet presets appear after registration |
| Today/month electricity cost and current hourly rate | Sensors in JPY and JPY/kWh |
| Time-of-day electricity prices | `set_electricity_tariff` with 24 hourly rates |
| Air and daily/monthly cost history | `get_history` response action with pagination |
| Outdoor weather, pollen, PM2.5 forecast, yellow sand and laundry forecast | Sensors plus `get_weather` response action, using the device's registered location |
| Device information and links | HA device page and link to Sharp's webpage |

KI-PX70 does not expose custom AI tuning, an on/off timer, continuous percentage fan speed, CO₂, particle counts or a standalone child-lock control in this account's webpage. These are not offered as guessed controls. Cat mode can enable child lock when an eligible cat is registered. PCI unit replacement still requires the physical procedure described by Sharp. Purchase/help pages and Sharp account management remain links rather than device controls. See the [authenticated feature audit](docs/feature-review-2026-10-07.md).

## Installation and update

Add this repository to [HACS custom repositories](https://hacs.xyz/docs/faq/custom_repositories/) as an integration, or copy `custom_components/cocoro_air` into HA's `custom_components` directory. Restart Home Assistant after updating Python files.

In **Settings → Devices & services → Add integration**, choose **Cocoro Air**, enter your Sharp email/password, then select your devices. Existing temperature/humidity unique IDs and device identifiers are preserved. The temporary session cookie used for investigation is not part of the integration; normal account login renews expired sessions, and HA offers reauthentication if required.

If Sharp requires updated terms or another account confirmation, complete it at the [official webpage](https://cocoroplusapp.jp.sharp/air), then reload the integration.

Device state refreshes every 60 seconds, and optional cloud information every 15 minutes. Commands refresh the device afterward. The refresh button and `get_cloud_info` force a cloud refresh. Sharp's cloud may take time to report a command result. Optional cloud failures do not disable the basic device controls.

## Actions

Actions are available under **Developer tools → Actions** in domain `cocoro_air`. Select a configured HA device; `device_id` may be omitted when exactly one device is configured. Raw Sharp device IDs are also accepted. Read actions require a response variable in scripts.

Read air history:

```yaml
action: cocoro_air.get_history
data:
  kind: air
  from_time: "2026-10-07T00:00:00+09:00"
  to_time: "2026-10-07T23:59:59+09:00"
  count: 1000
  offset: 0
response_variable: air_history
```

Use `cost_daily` or `cost_monthly` for electricity history. Dates must include a timezone; electricity periods follow Sharp's Japanese calendar. The response includes normalized records and the vendor count. Historical records are returned as data; HA's recorder records current sensors going forward.

Read capabilities, maintenance, pets, notifications and all 24 rates:

```yaml
action: cocoro_air.get_cloud_info
response_variable: sharp_info
```

Set notification bounds (use `null` to clear an individual bound):

```yaml
action: cocoro_air.set_notifications
data:
  preferences:
    temperature: true
    temperature_lower: 10
    temperature_upper: 30
```

Register a pet. To edit, include its cloud `pet_id` from `get_cloud_info` (`pets` → the pet's `0x00` object → `0x00` ID) and all visible fields:

```yaml
action: cocoro_air.set_pet
data:
  name: Momo
  species: cat
  sex: female
  breed: ""
```

`delete_pet` accepts `pet_id`. Pet presets depend on registered species and cloud home fit. `set_electricity_tariff` accepts `hourly_prices`: a list of 24 prices for hours 0–23, each 0–99.4 JPY/kWh with at most three decimal places. Existing opaque tariff metadata is retained.

Record actual maintenance:

```yaml
action: cocoro_air.maintain_supply
data:
  supply: dust_filter
  action: clean
```

`replace` is supported for dust, deodorizing and humidifying filters and the Ag+ ion cartridge, according to the official remote reset procedure. Replacement changes usage counters. Use these actions only after the corresponding maintenance. `set_prefilter` accepts a supported disposable `supply` and `active: true/false`.

Notification settings configure Sharp's notifications; they do not create HA notifications. HA automations can use the new measurements and care sensors separately.

## Development and verification

Run tests in an environment with `homeassistant` and `httpx` installed:

```sh
python -m unittest discover -s tests -v
```

Tests cover official protocol values, capability gating, HTTP/business errors, session renewal, concurrent notification updates, cloud payloads, entities, services, reauthentication and complete platform setup/unload. Without HA installed, HA-specific test modules are skipped. All 71 tests pass on HA 2024.2.5 and 2026.8.1; automated tests contain synthetic data and no account credentials.

Live KI-PX70 verification on HA 2026.8.1 loaded 55 entities and nine actions, preserved the existing temperature/humidity entity IDs, and successfully read cloud settings and air history. Power on/off was verified through HA with state readback, then the device was restored to its original off state. An initial cloud rejection did not recur after restarting HA; its cause remains unconfirmed. Consumable resets, pet deletion and tariff changes were checked through protocol tests rather than applied to the real account.
