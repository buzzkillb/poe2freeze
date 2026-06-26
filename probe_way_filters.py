import sys, json, urllib.request
sys.path.insert(0, r'C:\Users\travanx\Dropbox\projects\poe2\ninja')
league = 'Runes of Aldur'
encoded = league.replace(' ', '%20')

# Try different query approaches
queries = [
    # Tier 15 + packsize 20
    {'status': {'option': 'online'},
     'filters': {'map_filters': {'filters': {
         'map_tier': {'min': 15, 'max': 15},
         'map_packsize': {'min': 20}
     }}}},
    # Tier 15 + packsize 30
    {'status': {'option': 'online'},
     'filters': {'map_filters': {'filters': {
         'map_tier': {'min': 15, 'max': 15},
         'map_packsize': {'min': 30}
     }}}},
    # Tier 15 + packsize 40
    {'status': {'option': 'online'},
     'filters': {'map_filters': {'filters': {
         'map_tier': {'min': 15, 'max': 15},
         'map_packsize': {'min': 40}
     }}}},
]

for i, q in enumerate(queries):
    body = {'query': q, 'sort': {'price': 'asc'}}
    url = f'https://www.pathofexile.com/api/trade2/search/{encoded}'
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                                  headers={'User-Agent': 'OAuth poe2ninja/1.0', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            ids = data.get('result', [])[:5]
            if ids:
                url2 = f'https://www.pathofexile.com/api/trade2/fetch/{",".join(ids)}?query={data["id"]}'
                req2 = urllib.request.Request(url2, headers={'User-Agent': 'OAuth poe2ninja/1.0'})
                with urllib.request.urlopen(req2, timeout=15) as resp2:
                    items = json.loads(resp2.read())['result']
                    prices = []
                    for it in items:
                        p = it.get('listing', {}).get('price', {})
                        if p:
                            prices.append(f"{p.get('amount', 0)} {p.get('currency', '')}")
                    print(f"Q{i+1} packsize>={q['filters']['map_filters']['filters']['map_packsize']['min']}: total={data.get('total', 0)}, top 5 prices: {prices}")
            else:
                print(f"Q{i+1}: no results")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()[:100]
        print(f"Q{i+1}: HTTP {e.code} - {body_text}")
    except Exception as e:
        print(f"Q{i+1}: {e}")
    import time; time.sleep(2)