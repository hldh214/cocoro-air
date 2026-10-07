"""Validated HA actions for records and cloud configuration."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict
import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from .const import DOMAIN
from .cloud import (notification_payload,pet_payload,tariff_payload,decode_tariff,
                    supplies_reset_payload,supplies_action_commands,decode_cost_records,SUPPLY_TYPES)
from .protocol import parse_status

SERVICE_NAMES = ('get_cloud_info','get_history','get_weather','set_pet','delete_pet',
                 'set_notifications','set_electricity_tariff','maintain_supply','set_prefilter')
BASE_SCHEMA = {vol.Optional('device_id'):str}


def resolve_coordinator(hass,data):
    all_c = [c for entry in hass.data.get(DOMAIN,{}).values()
             for c in entry['coordinators'].values()]
    requested = data.get('device_id')
    if not requested:
        if len(all_c)==1:
            return all_c[0]
        raise HomeAssistantError('Choose a Cocoro Air device')
    for c in all_c:
        if c.device_id==requested:
            return c
    registry = dr.async_get(hass) if hasattr(hass,'helpers') or hasattr(hass,'bus') else None
    device = registry.async_get(requested) if registry else None
    if device:
        identifiers={identifier for domain,identifier in device.identifiers if domain==DOMAIN}
        for c in all_c:
            if c.device_id in identifiers:
                return c
    raise HomeAssistantError('Device is not a selected Cocoro Air device')


def format_api_datetime(value, wall_calendar=False):
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Include a timezone in the date and time')
    if wall_calendar:
        dt = dt.astimezone(ZoneInfo('Asia/Tokyo')).replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec='milliseconds').replace('+00:00','Z')


def history_properties(kind):
    if kind=='air':
        return [{'apg':'0x01','apc':['0x20'],'epc_ext':[{'opc':'k1'},{'opc':'k2'},{'opc':'k3'}]}]
    if kind in ('cost_daily','cost_monthly'):
        return [{'apg':'0x01','apc':['0x40'],'code':{'0x40':{
            '0x00':'0x00' if kind=='cost_daily' else '0x01','0x01':'0x00'}}}]
    raise ValueError('Unknown history type')


def first_record(body):
    rows=body.get('data') or []
    return rows[0] if rows else {}


def async_setup_services(hass):
    if hass.services.has_service(DOMAIN,'get_cloud_info'):
        return

    async def handle(call):
        c=resolve_coordinator(hass,call.data)
        data=dict(call.data)
        data.pop('device_id',None)
        try:
            if call.service=='get_cloud_info':
                c._cloud_updated=0
                await c.async_request_refresh()
                state=c.data
                return {'model':c.model_name,'capabilities':c.spec,
                        'modes':c.modes,'supplies':state.get('supplies',{}),
                        'pets':state.get('pets',[]),'notifications':state.get('notifications'),
                        'hourly_tariff':decode_tariff(first_record(state.get('tariff') or {}))}
            if call.service=='get_weather':
                return await c.async_api(c.api.get_weather,c.device,data.get('date'))
            if call.service=='get_history':
                wall_calendar = data['kind'] != 'air'
                start=format_api_datetime(data['from_time'],wall_calendar=wall_calendar)
                end=format_api_datetime(data['to_time'],wall_calendar=wall_calendar)
                if start>end:
                    raise ValueError('from_time must precede to_time')
                body=await c.async_api(c.api.history,c.device_id,history_properties(data['kind']),
                                       start,end,data.get('count',1000),data.get('offset',0))
                if data['kind']!='air':
                    return {'records':decode_cost_records(body),'count':body.get('count')}
                grouped=defaultdict(list)
                for row in body.get('data',[]):
                    grouped[row.get('time')].append(row)
                records=[]
                for time,rows in sorted(grouped.items(),key=lambda x:x[0] or ''):
                    status=parse_status({'data':rows},c.spec)
                    status.pop('properties',None)
                    records.append({'time':time,**status})
                return {'records':records,'count':body.get('count')}
            if call.service=='set_pet':
                if not c.spec.get('hasPetMode'):
                    raise ValueError('Pet mode is unsupported')
                pet_id=data.pop('pet_id',None)
                current=await c.async_api(c.api.get_pets,c.device_id)
                pets=current.get('data',[])
                if pet_id and not any(p.get('0x00',{}).get('0x00')==pet_id for p in pets):
                    raise ValueError('Pet ID does not belong to this device')
                if not pet_id and len(pets)>=10:
                    raise ValueError('Sharp supports at most ten pets')
                # All visible purifier fields required on update; advanced fields preserved.
                fields={key:data[key] for key in ('name','species','sex','breed') if key in data}
                payload=pet_payload(fields,pet_id)
                if pet_id:
                    existing=next(p['0x00'] for p in pets if p.get('0x00',{}).get('0x00')==pet_id)
                    new=payload[0]['code']['0x00']
                    for key in ('0x10','0x11','0x12','0x13'):
                        if key in existing:
                            new[key]=existing[key]
                    age = existing.get('0x05')
                    if data['species'] == 'dog' or age in ('0x00','0x02'):
                        if age is not None:
                            new['0x05'] = age
                return await c.async_cloud_write(c.api.write_pet,c.device_id,payload)
            if call.service=='delete_pet':
                pets=(await c.async_api(c.api.get_pets,c.device_id)).get('data',[])
                if not any(p.get('0x00',{}).get('0x00')==data['pet_id'] for p in pets):
                    raise ValueError('Pet ID does not belong to this device')
                return await c.async_cloud_write(c.api.delete_pet,c.device_id,data['pet_id'])
            if call.service=='set_notifications':
                patch=data['preferences']
                allowed={'air_cleaner','temperature','temperature_lower','temperature_upper'}
                if c.spec.get('hasHumanSensor'):allowed.add('human')
                if c.spec.get('canSpeek'):allowed.add('advertising')
                if set(patch)-allowed:
                    raise ValueError('Notification is not supported by this device')
                return await c.async_set_notifications(patch)
            if call.service=='set_electricity_tariff':
                current=await c.async_api(c.api.get_tariff,c.device_id)
                payload=tariff_payload(data['hourly_prices'],first_record(current))
                return await c.async_cloud_write(c.api.control_properties,c.device_id,payload)
            if call.service in ('maintain_supply','set_prefilter'):
                name=data['supply']
                if name not in c.data.get('supplies',{}):
                    raise ValueError('Supply does not exist on this device')
                timestamp=datetime.now().astimezone().isoformat(timespec='seconds')
                if call.service=='set_prefilter':
                    if name not in ('prefilter','humidifying_prefilter'):
                        raise ValueError('Choose a disposable prefilter')
                    return await c.async_cloud_write(c.api.write_supplies,c.device_id,
                         supplies_reset_payload(name,timestamp,data['active']))
                action=data['action']
                if action=='replace' and name not in ('dust_filter','deodorizing_filter','humidifying_filter','ion_cartridge'):
                    raise ValueError('Replacement is not remotely available for this supply')
                commands=supplies_action_commands(name,action,c.model_name)
                if commands:
                    await c.async_cloud_write(c.api.control,c.device,commands)
                if name=='ion_cartridge' and action=='replace':
                    return {'completed':True}
                active=c.data['supplies'][name].get('active',False)
                return await c.async_cloud_write(c.api.write_supplies,c.device_id,
                    supplies_reset_payload(name,timestamp,active))
        except (ValueError,TypeError,KeyError) as err:
            raise HomeAssistantError(str(err)) from err
        raise HomeAssistantError('Unsupported Cocoro Air action')

    schemas={
        'get_cloud_info':{},
        'get_weather':{vol.Optional('date'):str},
        'get_history':{vol.Required('kind'):vol.In(['air','cost_daily','cost_monthly']),
                       vol.Required('from_time'):str,vol.Required('to_time'):str,
                       vol.Optional('count',default=1000):vol.All(int,vol.Range(min=1,max=1000)),
                       vol.Optional('offset',default=0):vol.All(int,vol.Range(min=0,max=100000))},
        'set_pet':{vol.Optional('pet_id'):str,vol.Required('name'):str,
                   vol.Required('species'):vol.In(['dog','cat']),vol.Required('sex'):vol.In(['male','female']),
                   vol.Optional('breed',default=''):str},
        'delete_pet':{vol.Required('pet_id'):str},
        'set_notifications':{vol.Required('preferences'):dict},
        'set_electricity_tariff':{vol.Required('hourly_prices'):[vol.Coerce(float)]},
        'maintain_supply':{vol.Required('supply'):vol.In(list(SUPPLY_TYPES)),
                           vol.Required('action'):vol.In(['clean','replace'])},
        'set_prefilter':{vol.Required('supply'):vol.In(['prefilter','humidifying_prefilter']),
                         vol.Required('active'):bool},
    }
    for name in SERVICE_NAMES:
        response=SupportsResponse.ONLY if name.startswith('get_') else SupportsResponse.OPTIONAL
        hass.services.async_register(DOMAIN,name,handle,
            schema=vol.Schema({**BASE_SCHEMA,**schemas[name]}),supports_response=response)
