import sys, json, urllib.request
sys.path.insert(0, r'C:\Users\travanx\Dropbox\projects\poe2\ninja')
league = 'Runes of Aldur'
encoded = league.replace(' ', '%20')
# Test if map_quantity is the field for Waystone Drop Chance
for field in ['map_quantity', 'map_bonus', 'map_gold', 'map_effectiveness']:
    body = {'query': {
        'status': {'option': 'online'},
        'filters': {'map_filters': {'filters': {
            'map_tier': {'min': 15, 'max': 15},
            field: {'min': 50}
        }}}},
        'sort': {'price': 'asc'}}
    url = f'https://www.pathofexile.com/api/trade2/search/{encoded}'
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                                  headers={'User-Agent': 'OAuth poe2ninja/1.0', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            print(f'{field} min=50: total={data.get("total")}')
    except urllib.error.HTTPError as e:
        print(f'{field}: HTTP {e.code} - {e.read().decode()[:80]}')
    except Exception as e:
        print(f'{field}: {e}')
    import time; time.sleep(2)