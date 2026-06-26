import sys, json, urllib.request
sys.path.insert(0, r'C:\Users\travanx\Dropbox\projects\poe2\ninja')
league = 'Runes of Aldur'
encoded = league.replace(' ', '%20')

# Test EXACTLY the user's query
# From screenshot: T15, Packsize 19, IIR 42, Monster Effect 42, Drop Chance 145, Corrupted
body = {'query': {
    'status': {'option': 'online'},
    'filters': {
        'map_filters': {'filters': {
            'map_tier': {'min': 15, 'max': 15},
            'map_packsize': {'min': 19},
            'map_iir': {'min': 42},
            'map_bonus': {'min': 145}
        }},
        'trade_filters': {'filters': {'collapse': {'option': 'true'}}},
        'misc_filters': {'filters': {'corrupted': {'option': 'true'}}}
    }},
    'sort': {'price': 'asc'}}
url = f'https://www.pathofexile.com/api/trade2/search/{encoded}'
req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                              headers={'User-Agent': 'OAuth poe2ninja/1.0', 'Content-Type': 'application/json'})
import time
time.sleep(2)
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read())
    print(f'Total: {data.get("total")}')
    ids = data.get('result', [])[:10]
    url2 = f'https://www.pathofexile.com/api/trade2/fetch/{",".join(ids)}?query={data["id"]}'
    req2 = urllib.request.Request(url2, headers={'User-Agent': 'OAuth poe2ninja/1.0'})
    with urllib.request.urlopen(req2, timeout=15) as resp2:
        items = json.loads(resp2.read())['result']
        for it in items:
            p = it.get('listing', {}).get('price', {})
            acc = it.get('listing', {}).get('account', {}).get('name', '?')
            ch = p.get('amount', 0) * {'exalted': 1.0, 'divine': 372.0, 'chaos': 1/36.81}.get(p.get('currency'), 1.0)
            print(f'  {ch:>10.2f} ex ({p.get("amount")} {p.get("currency")}) - {acc}')