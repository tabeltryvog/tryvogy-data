"""Разова перевірка API UkraineAlarm: які поля віддає, чи є рівні загрози, яка глибина історії.
Ключ береться з секрету UKRAINEALARM_KEY і НІДЕ не друкується."""
import json, os, urllib.request, datetime, time
KEY = os.environ['UKRAINEALARM_KEY']
BASE = 'https://api.ukrainealarm.com'
def get(path):
    time.sleep(20)                       # API обмежує частоту запитів
    req = urllib.request.Request(BASE + path, headers={'Authorization': KEY, 'Accept': 'application/json', 'User-Agent': 'tabel-tryvog/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return getattr(e, 'code', 0), str(e)[:200]
out = {'checked': datetime.datetime.utcnow().isoformat()[:16] + 'Z', 'calls': {}}
prev = json.load(open('data/ua_probe.json', encoding='utf-8')) if os.path.exists('data/ua_probe.json') else {}
st, regions = (200, None) if prev.get('cities') else get('/api/v3/regions')
out['calls']['regions'] = st
cities = {}
want = ['Київ', 'Дніпро', 'Харків', 'Львів', 'Запоріжжя', 'Вінниця', 'Чернігів', 'Житомир', 'Суми', 'Одеса']
ORDER = ['Київ', 'Харків', 'Дніпро']          # спершу три міста, решта — наступним запуском
def walk(node, parent=''):
    for r in node if isinstance(node, list) else []:
        name = r.get('regionName', '')
        for w in want:
            if name in (w, 'м. ' + w, w + ' (місто)', 'м.' + w) or name.startswith('м. ' + w):
                cities.setdefault(w, []).append({'id': r.get('regionId'), 'name': name, 'type': r.get('regionType'), 'parent': parent})
        walk(r.get('regionChildIds') or [], name)
if isinstance(regions, dict):
    walk(regions.get('states') or [])
out['cities'] = cities or prev.get('cities', {})
cities = out['cities']
st, active = get('/api/v3/alerts')
out['calls']['alerts'] = st
out['active_sample'] = active[:3] if isinstance(active, list) else active
for w in ORDER:
    lst = cities.get(w) or []
    if not lst: continue
    rid = lst[0]['id']
    st, hist = get('/api/v3/alerts/regionHistory?regionId=%s' % rid)
    out['calls']['history_' + w] = st
    if isinstance(hist, list):
        alarms = [a for h in hist for a in (h.get('alarms') or [])] if hist and isinstance(hist[0], dict) and 'alarms' in hist[0] else hist
        out['history_' + w] = {'count': len(alarms), 'fields': sorted({k for a in alarms for k in a}) if alarms else [],
                                'first': alarms[-1] if alarms else None, 'last': alarms[0] if alarms else None}
    else:
        out['history_' + w] = hist
json.dump(out, open('data/ua_probe.json', 'w'), ensure_ascii=False, indent=1)
print('ok', {k: v for k, v in out['calls'].items()})
