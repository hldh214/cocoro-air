"""Pure encoders and decoders for the official COCORO AIR cloud controls."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from math import floor, isfinite

SUPPLY_TYPES = {
    'dust_filter': '0x00', 'deodorizing_filter': '0x01',
    'humidifying_filter': '0x02', 'ion_cartridge': '0x10',
    'pci_unit': '0x11', 'ac_filter_care': '0x20', 'dust_box': '0x30',
    'back_panel': '0x40', 'air_filter': '0x50',
    'prefilter': '0x60', 'humidifying_prefilter': '0x61',
}
_LIFE_FIELDS = {
    'dust_filter': ('dustFilterLimit', 'dustFilterUsed'),
    'deodorizing_filter': ('smellFilterLimit', 'smellFilterUsed'),
    'humidifying_filter': ('humidFilterLimit', 'humidFilterUsed'),
    'ion_cartridge': ('ionUnitLimit', 'agIonFilterUsed'),
    'pci_unit': ('pciUnitLimit', 'pciUnitUsed'),
}


def _number(value):
    """JavaScript Number semantics for the API's numeric and hex values."""
    if isinstance(value, str) and value.lower().startswith('0x'):
        return int(value, 16)
    return float(value)


def decode_tariff(record):
    """Return 24 hourly electricity rates in JPY/kWh from latest APC 50."""
    entries = record.get('0x50', [])
    if not entries or len(entries[-1].get('0x11', [])) != 24:
        return []
    return [_number(value) / 1000 for value in entries[-1]['0x11']]


def tariff_payload(hourly, record):
    """Encode an hourly tariff while preserving its opaque cloud metadata."""
    if len(hourly) != 24:
        raise ValueError('Exactly 24 hourly prices are required')
    encoded = []
    for value in hourly:
        try:
            rate = Decimal(str(value))
            if not rate.is_finite() or not 0 <= rate <= Decimal('99.4'):
                raise ValueError('Tariffs must be between 0 and 99.4 JPY/kWh')
            millis = rate * 1000
            if millis != millis.to_integral_value():
                raise ValueError('Tariffs support at most three decimal places')
        except InvalidOperation as exc:
            raise ValueError('Invalid tariff') from exc
        encoded.append(f'0x{int(millis):08X}')
    entries = record.get('0x50', [])
    if not entries or '0x10' not in entries[-1]:
        raise ValueError('Fetch the current tariff metadata before updating')
    return [{'apg': '0x01', 'code': {'0x50': {
        '0x00': '0x00', '0x10': entries[-1]['0x10'], '0x11': encoded,
    }}}]


def notification_payload(device_id, current, patch):
    """Merge a partial change without resetting unrelated cloud preferences."""
    booleans = {'operation_info', 'temperature', 'air_cleaner', 'human',
                'air_conditioner', 'remocon', 'advertising', 'co2_concentration'}
    thresholds = {'temperature_lower', 'temperature_upper', 'co2_ppm'}
    if set(patch) - booleans - thresholds:
        raise ValueError('Unknown notification preference')
    data = {key: deepcopy(value) for key, value in current.items() if key in booleans or key in {'temperature_detail', 'co2_concentration_detail'}}
    for key, value in patch.items():
        if key in booleans:
            if not isinstance(value, bool):
                raise ValueError('Notification switches must be booleans')
            data[key] = value
        else:
            detail_name = 'co2_concentration_detail' if key == 'co2_ppm' else 'temperature_detail'
            detail_key = 'ppm' if key == 'co2_ppm' else key
            if not isinstance(data.get(detail_name), dict):
                data[detail_name] = {}
            if value is None:
                data[detail_name].pop(detail_key, None)
                if not data[detail_name]:
                    data.pop(detail_name)
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError('Notification thresholds must be integers')
            if key == 'co2_ppm':
                if not 400 <= value <= 5000 or value % 100:
                    raise ValueError('CO2 threshold must be 400–5000 in steps of 100')
                data.setdefault('co2_concentration_detail', {})['ppm'] = value
            else:
                if not 0 <= value <= 40:
                    raise ValueError('Temperature thresholds must be 0–40 Celsius')
                data.setdefault('temperature_detail', {})[key] = value
    detail = data.get('temperature_detail') or {}
    lower, upper = detail.get('temperature_lower'), detail.get('temperature_upper')
    if lower is not None and upper is not None and lower >= upper:
        raise ValueError('Lower temperature must be below upper temperature')
    return {'bff_device_id': device_id, 'data': data}


def pet_payload(fields, pet_id=None):
    """Build a cloud pet create/update property from human-readable fields."""
    allowed = {'name', 'species', 'sex', 'breed', 'age', 'head', 'size', 'hair', 'body'}
    if set(fields) - allowed:
        raise ValueError('Unknown pet field')
    name, breed = fields.get('name', ''), fields.get('breed', '')
    if not isinstance(name, str) or not name.strip() or len(name) > 20:
        raise ValueError('Pet name must contain 1–20 characters')
    if not isinstance(breed, str) or len(breed) > 20:
        raise ValueError('Pet breed must contain at most 20 characters')
    choices = {
        'species': ('0x02', {'dog': '0x00', 'cat': '0x01'}, 'dog'),
        'sex': ('0x04', {'male': '0x00', 'female': '0x01'}, 'male'),
        'head': ('0x10', {'short': '0x01', 'normal': '0x00'}, 'short'),
        'size': ('0x11', {'small': '0x01', 'medium_large': '0x00'}, 'small'),
        'hair': ('0x12', {'long': '0x00', 'short': '0x01'}, 'long'),
        'body': ('0x13', {'slim': '0x00', 'normal': '0x01', 'fat': '0x02'}, 'slim'),
    }
    pet = {'0x01': name, '0x03': breed}
    for key, (code, mapping, default) in choices.items():
        value = fields.get(key, default)
        if value not in mapping:
            raise ValueError(f'Invalid pet {key}')
        pet[code] = mapping[value]
    age_choices = {'kitten_adult': '0x00', 'senior': '0x02'} if fields.get('species') == 'cat' else {'puppy': '0x00', 'adult': '0x01', 'senior': '0x02'}
    age = fields.get('age', next(iter(age_choices)))
    if age not in age_choices:
        raise ValueError('Invalid age category for species')
    pet['0x05'] = age_choices[age]
    if pet_id is not None:
        pet['0x00'] = pet_id
    return [{'apg': '0x01', 'code': {'0x00': pet}}]


def parse_supplies(record, status, spec):
    """Decode cloud care metadata and remaining life from actual device counters."""
    status = dict(status.get('properties', status))
    raw = status.get('k1', {})
    for field, key in {'dustFilterUsed': 's8', 'smellFilterUsed': 's9',
                       'humidFilterUsed': 's10', 'agIonFilterUsed': 's11',
                       'pciUnit1Used': 's4', 'pciUnit2Used': 's5',
                       'totalOperatingTime': 's3', 'totalHumidificationAmount': 's12'}.items():
        if field not in status and key in raw:
            try:
                status[field] = int(str(raw[key]), 16)
            except (TypeError, ValueError):
                status[field] = None
    if 'pciUnitUsed' not in status and status.get('pciUnit1Used') is not None:
        status['pciUnitUsed'] = max(status['pciUnit1Used'], status.get('pciUnit2Used') or 0) if spec.get('hasPciTwiceUnit') else status['pciUnit1Used']
    raw_k2 = status.get('k2', {})
    for field, key, expected in [('needMaintenanceHumidFilter', 's10', '01'),
                                 ('needMaintenancePciUnit', 's17', 'FF'),
                                 ('needMaintenanceDustbox', 's14', 'FF')]:
        if field not in status and key in raw_k2:
            status[field] = str(raw_k2[key]).upper() == expected
    error = str(status.get('0x86') or '').removeprefix('0x').upper()
    if len(error) >= 12 and all(char in '0123456789ABCDEF' for char in error):
        status.setdefault('isCareError', bool(int(error[10:12], 16) & 4))
        status.setdefault('isUnitDateError', bool(int(error[8:10], 16) & 4))
        status.setdefault('isUnitOutError', bool(int(error[8:10], 16) & 2))
    result = {}
    reverse = {code: name for name, code in SUPPLY_TYPES.items()}
    for entry in record.get('0x10', []):
        name = reverse.get(entry.get('0x00'))
        if name is None:
            continue
        factor = _safe_number(entry.get('0x02'))
        multiplier = None if '0x02' in entry and (factor is None or factor < 0) else (factor / 10 if factor else 1)
        remaining = None
        if name in _LIFE_FIELDS:
            life_key, used_key = _LIFE_FIELDS[name]
            life, used = _safe_number(spec.get(life_key)), _safe_number(status.get(used_key))
            if life is not None and used is not None and multiplier is not None and life >= 0 and used >= 0:
                life, used = _number(life), _number(used)
                remaining = max(0, min(100, floor(100 * (life - used) / (life * multiplier)))) if life > 0 else 0
            if name == 'pci_unit' and (status.get('isUnitOutError') or status.get('isUnitDateError')):
                remaining = 0
        active = entry.get('0x30') == '0x01'
        interval = _safe_number(entry.get('0x11'))
        baseline = _safe_number(entry.get('0x20'))
        operating = _safe_number(status.get('totalOperatingTime'))
        needs_cleaning = None
        if name == 'back_panel' and operating is not None and baseline is not None and interval is not None and interval > 0:
            needs_cleaning = not active and _number(operating) - baseline >= interval * 60
        elif name == 'humidifying_filter' and 'needMaintenanceHumidFilter' in status:
            needs_cleaning = bool(status['needMaintenanceHumidFilter'])
        elif name == 'pci_unit':
            if status.get('isCareError'):
                needs_cleaning = True
            elif spec.get('seriiesCode', 0) >= 10 and spec.get('canSpeek'):
                needs_cleaning = status.get('needMaintenancePciUnit')
            elif operating is not None and baseline is not None and interval is not None and interval > 0:
                needs_cleaning = _number(operating) - baseline >= interval * 60 and remaining not in (0, 99, 100)

        result[name] = {'remaining': remaining, 'model': entry.get('0x01'),
                        'last_cleaned': entry.get('0x21'), 'needs_cleaning': needs_cleaning,
                        'active': active, 'cleaning_interval_hours': interval}
    return result


def supplies_reset_payload(supply_type, timestamp, active=False):
    """Record cloud care; this deliberately does not reset appliance counters."""
    if supply_type not in SUPPLY_TYPES:
        raise ValueError('Unknown supply type')
    return [{'apg': '0x02', 'code': {'0x10': {
        '0x00': SUPPLY_TYPES[supply_type], '0x21': timestamp,
        '0x30': '0x01' if active else '0x00',
    }}}]


def supplies_action_commands(supply_type, action, model=None, device_type='ap'):
    """Appliance OPC reset commands implemented by the official replacement UI.

    Empty commands mean cloud metadata only; some counters require the physical
    reset button (humidifying cleaning except KIM851, PCI, mechanical dust box).
    """
    if supply_type not in SUPPLY_TYPES or action not in {'clean', 'replace'}:
        raise ValueError('Invalid supply action')
    if device_type == 'ac':
        return [{'opc': 'k3', 'odt': {'s2': '0000'}}] if action == 'replace' and supply_type == 'dust_filter' else []
    if action == 'clean':
        code = '10' if supply_type == 'humidifying_filter' and model == 'KIM851' else None
    else:
        code = {'dust_filter': '08', 'deodorizing_filter': '04',
                'humidifying_filter': '12' if model == 'KIM851' else '02',
                'ion_cartridge': '01'}.get(supply_type)
    return [{'opc': 'k3', 'odt': {'s4': code}}] if code else []


def decode_cost_records(body):
    """Decode Sharp's daily/monthly milli-JPY history, retaining source dates."""
    return [{'time': row['time'], 'cost': _number(row['0x40']['0x00']) / 1000}
            for row in body.get('data', []) if 'time' in row and '0x40' in row]


def _safe_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = _number(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def parse_weather(body, hour_jst):
    """Current three-hour forecast and today's zero-based environmental indices.

    Pollen: little/somewhat many/many/very many (0–3); PM2.5 and yellow sand:
    little/some/very much (0–2); laundry: not dry/hard to dry/dry/dry well (0–3).
    Missing forecasts remain unavailable.
    """
    if isinstance(hour_jst, bool) or not isinstance(hour_jst, int) or not 0 <= hour_jst <= 23:
        raise ValueError('JST hour must be an integer from 0 to 23')
    if not isinstance(body, dict):
        raise ValueError('Invalid weather response')
    if 'data' in body:
        rows = body.get('data') or []
        if not isinstance(rows, list):
            raise ValueError('Invalid weather records')
        record = rows[0] if rows else {}
    else:
        record = body
    if not isinstance(record, dict):
        raise ValueError('Invalid weather record')
    slots, days = record.get('0x30') or [], record.get('0x20') or []
    if not isinstance(slots, list) or not isinstance(days, list):
        raise ValueError('Invalid weather forecast arrays')
    slot = slots[hour_jst // 3] if len(slots) > hour_jst // 3 else {}
    daily = days[0] if days else {}
    if not isinstance(slot, dict) or not isinstance(daily, dict):
        raise ValueError('Invalid weather forecast slot')
    laundry = _safe_number(daily.get('0x08'))
    laundry_index = None
    if laundry is not None and 0 <= laundry <= 100:
        laundry_index = 0 if laundry <= 30 else 1 if laundry <= 50 else 2 if laundry <= 70 else 3
    return {
        'outdoor_temperature': _safe_number(slot.get('0x03')),
        'outdoor_humidity': _safe_number(slot.get('0x05')),
        'weather_code': slot.get('0x02'),
        'pollen': {'2': 0, '3': 1, '4': 2, '5': 3}.get(daily.get('0x06')),
        'pm25_forecast': {'1': 0, '2': 1, '3': 2}.get(daily.get('0x05')),
        'yellow_sand': {'1': 0, '2': 1, '3': 2}.get(daily.get('0x07')),
        'laundry': laundry_index,
    }
