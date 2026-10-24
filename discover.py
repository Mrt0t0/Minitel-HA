#!/usr/bin/env python3
"""Decouverte des entites HA -> sections devices / sensors de la configuration.

Les personnalisations existantes (nom, piece, visibilite) sont conservees ;
les entites disparues de HA sont gardees mais masquees (visible: false).

  python discover.py [--dry] [--force] [--config FICHIER] [--target FICHIER]

  --dry     affiche le resultat sans rien ecrire
  --force   ignore les personnalisations et repart des valeurs HA
  --config  configuration lue (URL, token, section discovery)
            defaut : $MINITEL_CONFIG ou config.yaml a cote du script
  --target  fichier ou ecrire devices / sensors
            defaut : $MINITEL_DISCOVER_TARGET ou le fichier --config
            (l'add-on HA ecrit dans /share/minitel-ha/config.yaml)
"""
import argparse
import asyncio
import os
from pathlib import Path

import aiohttp
import yaml

BASE    = Path(__file__).parent
TIMEOUT = aiohttp.ClientTimeout(total=30)

# Une seule requete pour toutes les pieces : "entity|piece" par ligne
AREAS_TPL = '{% for e in ids %}{{ e }}|{{ area_name(e) }}\n{% endfor %}'

ICONS = {'light': 'light', 'cover': 'cover', 'climate': 'climate', 'lock': 'lock',
         'media_player': 'media', 'fan': 'fan'}


def parse_areas(text):
    areas = {}
    for line in text.splitlines():
        eid, _, area = line.partition('|')
        area = area.strip()
        if eid.strip():
            areas[eid.strip()] = area if area and area.lower() != 'none' else 'Autres'
    return areas


def merge(found, existing, force, fields):
    """Fusionne les entites trouvees avec celles deja configurees."""
    seen, out = set(), []
    for item in found:
        ex = existing.get(item['entity'])
        seen.add(item['entity'])
        if ex and not force:
            item = {**item, **{k: ex[k] for k in fields if k in ex}}
        out.append(item)
    for eid, ex in existing.items():
        if eid not in seen:
            out.append({**ex, 'visible': False})
    return out


def select(states, disc):
    domains  = disc.get('domains', ['light', 'switch'])
    sen_cls  = disc.get('sensor_classes', ['temperature', 'humidity'])
    excl_kw  = disc.get('exclude_keywords', [])
    excl_ids = disc.get('exclude_entities', [])
    devs = [e for e in states
            if e['entity_id'].split('.')[0] in domains
            and not any(kw in e['entity_id'] for kw in excl_kw)
            and e['entity_id'] not in excl_ids]
    sens = [e for e in states
            if e['entity_id'].split('.')[0] == 'sensor'
            and e['attributes'].get('device_class') in sen_cls
            and e['entity_id'] not in excl_ids]
    return devs, sens


async def fetch(url, hdrs, ids_of):
    async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
        async with s.get(f'{url}/api/states', headers=hdrs) as r:
            if r.status != 200:
                raise SystemExit(f'[ERR] HA non joignable : HTTP {r.status}')
            states = await r.json()
        ids = ids_of(states)
        try:
            async with s.post(f'{url}/api/template', headers=hdrs,
                              json={'template': AREAS_TPL, 'variables': {'ids': ids}}) as r:
                areas = parse_areas(await r.text()) if r.status == 200 else {}
        except aiohttp.ClientError:
            areas = {}
    return states, areas


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--config', default=os.environ.get('MINITEL_CONFIG', BASE / 'config.yaml'))
    ap.add_argument('--target', default=os.environ.get('MINITEL_DISCOVER_TARGET'))
    args = ap.parse_args(argv)

    cfg_path = Path(args.config)
    target   = Path(args.target) if args.target else cfg_path
    cfg      = yaml.safe_load(open(cfg_path, encoding='utf-8')) or {}
    ha       = cfg.get('homeassistant') or {}
    url      = str(ha.get('url', '')).rstrip('/')
    hdrs     = {'Authorization': f'Bearer {ha.get("token", "")}',
                'Content-Type': 'application/json'}
    disc     = cfg.get('discovery') or {}

    def ids_of(states):
        devs, sens = select(states, disc)
        return [e['entity_id'] for e in devs + sens]

    states, areas = asyncio.run(fetch(url, hdrs, ids_of))
    devs, sens = select(states, disc)

    tgt = (yaml.safe_load(open(target, encoding='utf-8')) or {}) if target.exists() else {}
    existing_d = {d['entity']: d for d in (tgt.get('devices') or []) if d.get('entity')}
    existing_s = {s['entity']: s for s in (tgt.get('sensors') or []) if s.get('entity')}

    found_d = [{'entity': e['entity_id'],
                'name': e['attributes'].get('friendly_name', e['entity_id']),
                'area': areas.get(e['entity_id'], 'Autres'),
                'icon': ICONS.get(e['entity_id'].split('.')[0], 'switch'),
                'visible': True} for e in devs]
    found_s = [{'entity': e['entity_id'],
                'name': e['attributes'].get('friendly_name', e['entity_id']),
                'area': areas.get(e['entity_id'], 'Autres'),
                'unit': e['attributes'].get('unit_of_measurement', ''),
                'class': e['attributes'].get('device_class', 'sensor'),
                'visible': True} for e in sens]
    merged_d = merge(found_d, existing_d, args.force, ('name', 'area', 'icon', 'visible'))
    merged_s = merge(found_s, existing_s, args.force, ('name', 'area', 'unit', 'visible'))

    print(f'\n{len(devs)} appareils | {len(sens)} capteurs trouves dans HA\n')
    for d in found_d:
        print(f'  [{d["area"][:18]:<18}] {d["entity"]}')
    for s in found_s:
        print(f'  [{s["area"][:18]:<18}] {s["entity"]} ({s["unit"]})')

    if args.dry:
        print('\n[DRY RUN] rien ecrit')
        return
    tgt['devices'], tgt['sensors'] = merged_d, merged_s
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'w', encoding='utf-8') as f:
        yaml.dump(tgt, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f'\nOK {len(merged_d)} appareils + {len(merged_s)} capteurs -> {target}')
    print('   (les commentaires du fichier ne sont pas conserves ; redemarrez Minitel-HA)')


if __name__ == '__main__':
    main()
