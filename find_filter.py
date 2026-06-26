import sys, json, urllib.request
sys.path.insert(0, r'C:\Users\travanx\Dropbox\projects\poe2\ninja')
import time

league = 'Runes of Aldur'
encoded = league.replace(' ', '%20')
url = f'https://www.pathofexile.com/api/trade2/search/{encoded}'

# Test combinations of filters to find the one returning exactly 6
# From the screenshot: T15+, packsize 19+, IIR 42+, drop chance 145+, corrupted=yes
tests = [
    # T15 + packsize 19 + IIR 42 + corrupted (no drop chance filter)
    {'name': 'T15+pack19+iir42+corrupt',
     'body': {'query': {'status': {'option': 'online'},
              'filters': {
                  'map_filters': {'filters': {
                      'map_tier': {'min': 15},
                      'map_packsize': {'min': 19},
                      'map_iir': {'min': 42},
                  }},
                  'trade_filters': {'filters': {'collapse': {'option': 'true'}}},
                  'misc_filters': {'filters': {'corrupted': {'option': 'true'}}}}},
              'sort': {'price': 'asc'}}},

    # T15 + packsize 19 + IIR 42 (no corrupted)
    {'name': 'T15+pack19+iir42',
     'body': {'query': {'status': {'option': 'online'},
              'filters': {
                  'map_filters': {'filters': {
                      'map_tier': {'min': 15},
                      'map_packsize': {'min': 19},
                      'map_iir': {'min': 42},
                  }}},
              'sort': {'price': 'asc'}}},

    # T15 + packsize 19 + corrupted (no IIR)
    {'name': 'T15+pack19+corrupt',
     'body': {'query': {'status': {'option': 'online'},
              'filters': {
                  'map_filters': {'filters': {
                      'map_tier': {'min': 15},
                      'map_packsize': {'min': 19},
                  }},
                  'trade_filters': {'filters': {'collapse': {'option': 'true'}}},
                  'misc_filters': {'filters': {'corrupted': {'option': 'true'}}}}},
              'sort': {'price': 'asc'}}},

    # T15 + IIR 42 + corrupted
    {'name': 'T15+iir42+corrupt',
     'body': {'query': {'status': {'option': 'online'},
              'filters': {
                  'map_filters': {'filters': {
                      'map_tier': {'min': 15},
                      'map_iir': {'min': 42},
                  }},
                  'trade_filters': {'filters': {'collapse': {'option': 'true'}}},
                  'misc_filters': {'filters': {'corrupted': {'option': 'true'}}}}},
              'sort': {'price': 'asc'}}},

    # T15 + IIR 42 + drop 145 + corrupted
    {'name': 'T15+iir42+drop145+corrupt',
     'body': {'query': {'status': {'option': 'online'},
              'filters': {
                  'map_filters': {'filters': {
                      'map_tier': {'min': 15},
                      'map_iir': {'min': 42},
                      'map_bonus': {'min': 145},
                  }},
                  'trade_filters': {'filters': {'collapse': {'option': 'true'}}},
                  'misc_filters': {'filters': {'corrupted': {'option': 'true'}}}}},
              'sort': {'price': 'asc'}}},

    # T15 + packsize 19 + drop 145 + corrupted
    {'name': 'T15+pack19+drop145+corrupt',
     'body': {'query': {'status': {'option': 'online'},
              'filters': {
                  'map_filters': {'filters': {
                      'map_tier': {'min': 15},
                      'map_packsize': {'min': 19},
                      'map_bonus': {'min': 145},
                  }},
                  'trade_filters': {'filters': {'collapse': {'option': 'true'}}},
                  'misc_filters': {'filters': {'corrupted': {'option': 'true'}}}}},
              'sort': {'price': 'asc'}}},

    # T15 + packsize 19 + IIR 42 + drop 145 + corrupted
    {'name': 'T15+pack19+iir42+drop145+corrupt',
     'body': {'query': {'status': {'option': 'online'},
              'filters': {
                  'map_filters': {'filters': {
                      'map_tier': {'min': 15},
                      'map_packsize': {'min': 19},
                      'map_iir': {'min': 42},
                      'map_bonus': {'min': 145},
                  }},
                  'trade_filters': {'filters': {'collapse': {'option': 'true'}}},
                  'misc_filters': {'filters': {'corrupted': {'option': 'true'}}}}},
              'sort': {'price': 'asc'}}},
]

for t in tests:
    req = urllib.request.Request(url, data=json.dumps(t['body']).encode(), method='POST',
                                  headers={'User-Agent': 'OAuth poe2ninja/1.0', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            total = data.get('total', 0)
            print(f"{t['name']}: total={total}")
    except urllib.error.HTTPError as e:
        print(f"{t['name']}: HTTP {e.code} - {e.read().decode()[:60]}")
    except Exception as e:
        print(f"{t['name']}: {e}")
    time.sleep(2)