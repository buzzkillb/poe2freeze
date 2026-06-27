import sys, json, urllib.request
sys.path.insert(0, r'C:\Users\travanx\Dropbox\projects\poe2\ninja')
league = 'Runes of Aldur'
encoded = league.replace(' ', '%20')

body = {'query': {
    'status': {'option': 'online'},
    'stats': [{'type': 'and', 'filters': []}],
    'filters': {
        'type_filters': {'filters': {'category': {'option': 'map.waystone'}}},
        'map_filters': {'filters': {
            'map_tier': {'min': 15, 'max': 15},
            'map_packsize': {'min': 19},
            'map_iir': {'min': 42},
            'map_bonus': {'min': 145},
        }},
    }},
    'sort': {'price': 'asc'}}
url = f'https://www.pathofexile.com/api/trade2/search/{encoded}'
req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                              headers={'User-Agent': 'OAuth poe2ninja/1.0', 'Content-Type': 'application/json'})
import time; time.sleep(3)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        print(f'total: {data.get("total")}, ids: {len(data.get("result", []))}')
except urllib.error.HTTPError as e:
    print(f'HTTP {e.code}: {e.read().decode()[:200]}')