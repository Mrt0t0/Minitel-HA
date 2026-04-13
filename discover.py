import sys, yaml, asyncio, aiohttp
from pathlib import Path

BASE = Path(__file__).parent
cfg  = yaml.safe_load(open(BASE / 'config.yaml'))
HA_URL = cfg['homeassistant']['url']
HA_TOK = cfg['homeassistant']['token']
HDRS = {'Authorization': f'Bearer {HA_TOK}', 'Content-Type': 'application/json'}

disc     = cfg.get('discovery', {})
DOMAINS  = disc.get('domains', ['light', 'switch'])
SEN_CLS  = disc.get('sensor_classes', ['temperature', 'humidity'])
EXCL_KW  = disc.get('exclude_keywords', [])
EXCL_IDS = disc.get('exclude_entities', [])
FORCE    = '--force' in sys.argv
DRY_RUN  = '--dry' in sys.argv

async def area_of(s, eid):
    tpl = "{{ area_name('" + eid + "') }}"
    try:
        async with s.post(f'{HA_URL}/api/template', headers=HDRS, json={'template': tpl}) as r:
            v = (await r.text()).strip()
        return v if v and v not in ('None','none','') else 'Autres'
    except:
        return 'Autres'

async def run():
    async with aiohttp.ClientSession() as s:
        async with s.get(f'{HA_URL}/api/states', headers=HDRS) as r:
            if r.status != 200:
                print(f'[ERR] HA non joignable : {r.status}'); return
            states = await r.json()

    devices_raw = [e for e in states
                   if e['entity_id'].split('.')[0] in DOMAINS
                   and not any(kw in e['entity_id'] for kw in EXCL_KW)
                   and e['entity_id'] not in EXCL_IDS]
    sensors_raw = [e for e in states
                   if e['entity_id'].split('.')[0] == 'sensor'
                   and e['attributes'].get('device_class') in SEN_CLS]

    print(f"\n{'='*50}")
    print(f"  Découverte — {'FORCE' if FORCE else 'merge protégé'}")
    print(f"{'='*50}")
    print(f"  {len(devices_raw)} appareils | {len(sensors_raw)} capteurs\n")

    existing_devices = {d['entity']: d for d in (cfg.get('devices') or [])}
    existing_sensors = {s['entity']: s for s in (cfg.get('sensors') or [])}
    merged_devices, merged_sensors = [], []
    discovered_eids, discovered_sids = set(), set()

    async with aiohttp.ClientSession() as s:
        for e in devices_raw:
            eid = e['entity_id']
            fname = e['attributes'].get('friendly_name', eid)
            area  = await area_of(s, eid)
            icon  = 'light' if eid.startswith('light') else 'switch'
            ex    = existing_devices.get(eid, {})
            discovered_eids.add(eid)
            if FORCE or not ex:
                merged_devices.append({'entity': eid,'name': fname,'area': area,'icon': icon,'visible': True})
                print(f"  [{'F' if ex else 'N'}] {icon} [{area:<18}] {fname[:30]}")
            else:
                merged_devices.append({'entity': eid,'name': ex.get('name', fname),'area': ex.get('area', area),'icon': icon,'visible': ex.get('visible', True)})
                print(f"  [=] {icon} [{area:<18}] {ex.get('name', fname)[:30]}")
        for eid, d in existing_devices.items():
            if eid not in discovered_eids:
                d_copy = dict(d); d_copy['visible'] = False
                merged_devices.append(d_copy)
                print(f"  [X] [{d.get('area','?'):<18}] {d.get('name', eid)[:30]} → visible:false")

        for e in sensors_raw:
            eid = e['entity_id']
            fname = e['attributes'].get('friendly_name', eid)
            area  = await area_of(s, eid)
            ex    = existing_sensors.get(eid, {})
            discovered_sids.add(eid)
            if FORCE or not ex:
                merged_sensors.append({'entity': eid,'name': fname,'area': area,'unit': e['attributes'].get('unit_of_measurement',''),'class': e['attributes'].get('device_class','sensor'),'visible': True})
            else:
                merged_sensors.append({'entity': eid,'name': ex.get('name', fname),'area': ex.get('area', area),'unit': ex.get('unit',''),'class': ex.get('class','sensor'),'visible': ex.get('visible', True)})
        for eid, s2 in existing_sensors.items():
            if eid not in discovered_sids:
                s_copy = dict(s2); s_copy['visible'] = False
                merged_sensors.append(s_copy)

    print(f"\n  {len(merged_devices)} appareils | {len(merged_sensors)} capteurs")
    if DRY_RUN:
        print("  [DRY RUN] config.yaml non modifié"); return
    cfg['devices'] = merged_devices
    cfg['sensors'] = merged_sensors
    with open(BASE / 'config.yaml', 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print("✓ config.yaml mis à jour")

asyncio.run(run())
