#!/usr/bin/env python3
import yaml, asyncio, aiohttp
from pathlib import Path

BASE   = Path(__file__).parent
cfg    = yaml.safe_load(open(BASE / 'config.yaml'))
HA_URL = cfg['homeassistant']['url']
HA_TOK = cfg['homeassistant']['token']
HDRS   = {'Authorization': f'Bearer {HA_TOK}', 'Content-Type': 'application/json'}
disc   = (cfg.get('discovery') or {})
DOMAINS  = disc.get('domains', ['light', 'switch'])
SEN_CLS  = disc.get('sensor_classes', ['temperature', 'humidity'])
EXCL_KW  = disc.get('exclude_keywords', [])
EXCL_IDS = disc.get('exclude_entities', [])

async def area_of(s, eid):
    tpl = '{{ area_name("' + eid + '") }}'
    try:
        async with s.post(f'{HA_URL}/api/template', headers=HDRS,
                          json={'template': tpl}) as r:
            v = (await r.text()).strip()
        return v if v and v not in ('None', 'none', '') else 'Autres'
    except:
        return 'Autres'

async def run():
    async with aiohttp.ClientSession() as s:
        async with s.get(f'{HA_URL}/api/states', headers=HDRS) as r:
            if r.status != 200:
                print(f"[ERR] HA non joignable : {r.status}")
                return
            states = await r.json()

    devices_raw = [
        e for e in states
        if e['entity_id'].split('.')[0] in DOMAINS
        and not any(kw in e['entity_id'] for kw in EXCL_KW)
        and e['entity_id'] not in EXCL_IDS
    ]
    sensors_raw = [
        e for e in states
        if e['entity_id'].split('.')[0] == 'sensor'
        and e['attributes'].get('device_class') in SEN_CLS
    ]

    print(f"\n{len(devices_raw)} appareils | {len(sensors_raw)} capteurs\n")
    existing = {d['entity']: d for d in (cfg.get('devices') or [])}
    merged_devices, merged_sensors = [], []

    async with aiohttp.ClientSession() as s:
        for e in devices_raw:
            eid   = e['entity_id']
            fname = e['attributes'].get('friendly_name', eid)
            area  = await area_of(s, eid)
            icon  = 'light' if eid.startswith('light') else 'switch'
            ex    = existing.get(eid, {})
            merged_devices.append({
                'entity': eid, 'name': ex.get('name', fname),
                'area': ex.get('area', area), 'icon': ex.get('icon', icon),
                'visible': ex.get('visible', True),
            })
            sym = '💡' if icon == 'light' else '🔌'
            print(f"  {sym} [{area:<18}] {fname[:30]}")

        for e in sensors_raw:
            eid   = e['entity_id']
            fname = e['attributes'].get('friendly_name', eid)
            area  = await area_of(s, eid)
            merged_sensors.append({
                'entity': eid, 'name': fname, 'area': area,
                'unit': e['attributes'].get('unit_of_measurement', ''),
                'class': e['attributes'].get('device_class', 'sensor'),
                'visible': True,
            })
            print(f"  🌡 [{area:<18}] {fname[:30]} = {e['state']}")

    cfg['devices'] = merged_devices
    cfg['sensors'] = merged_sensors
    with open(BASE / 'config.yaml', 'w') as f:
        yaml.dump(cfg, f, allow_unicode=True,
                  default_flow_style=False, sort_keys=False)
    print(f"\n✓ {len(merged_devices)} appareils + {len(merged_sensors)} capteurs → config.yaml")

asyncio.run(run())
