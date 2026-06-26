import sys, json, urllib.request
sys.path.insert(0, r'C:\Users\travanx\Dropbox\projects\poe2\ninja')
league = 'Runes of Aldur'
encoded = league.replace(' ', '%20')

body = {'query': {
    'status': {'option': 'online'},
    'filters': {'map_filters': {'filters': {
        'map_tier': {'min': 15, 'max': 15},
        'map_packsize': {'min': 30}
    }}}},
    'sort': {'price': 'asc'}}
url = f'https://www.pathofexile.com/api/trade2/search/{encoded}'
req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                              headers={'User-Agent': 'OAuth poe2ninja/1.0', 'Content-Type': 'application/json'})
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read())
    ids = data.get('result', [])[:3]
    url2 = f'https://www.pathofexile.com/api/trade2/fetch/{",".join(ids)}?query={data["id"]}'
    req2 = urllib.request.Request(url2, headers={'User-Agent': 'OAuth poe2ninja/1.0'})
    with urllib.request.urlopen(req2, timeout=15) as resp2:
        items = json.loads(resp2.read())['result']
        for it in items:
            l = it.get('listing', {})
            p = l.get('price', {})
            o = l.get('offers', [])
            print(f"  Price: {p.get('amount')} {p.get('currency')}")
            print(f"  Account: {l.get('account', {}).get('name', '?')}")
            print(f"  Offers ({len(o)}):")
            for off in o:
                ex = off.get('exchange', {})
                it_p = off.get('item', {})
                print(f"    exchange: {ex.get('amount')} {ex.get('currency')}, item: {it_p.get('amount')} {it_p.get('currency', 'unknown')}")
            print()