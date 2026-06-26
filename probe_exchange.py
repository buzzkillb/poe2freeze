import sys, json
sys.path.insert(0, r'C:\Users\travanx\Dropbox\projects\poe2\ninja')
import urllib.request
import time

url = 'https://www.pathofexile.com/api/trade2/exchange/Runes%20of%20Aldur'
body = {'engine': 'new', 'query': {'status': {'option': 'online'}, 'have': ['divine'], 'want': ['exalted']}, 'sort': {'have': 'asc'}}
req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                              headers={'User-Agent': 'OAuth poe2ninja/1.0', 'Content-Type': 'application/json'})
time.sleep(3)
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read())
print('Live trade2 EXCHANGE rate (1 divine -> ? ex):')
for listing in list(data.get('result', {}).values())[:3]:
    offer = listing['listing']['offers'][0]
    print(f"  {offer['exchange']['amount']} ex for 1 divine")

print()
body = {'engine': 'new', 'query': {'status': {'option': 'online'}, 'have': ['exalted'], 'want': ['chaos']}, 'sort': {'have': 'asc'}}
req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                              headers={'User-Agent': 'OAuth poe2ninja/1.0', 'Content-Type': 'application/json'})
time.sleep(2)
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read())
print('Live trade2 EXCHANGE rate (1 ex -> ? chaos):')
for listing in list(data.get('result', {}).values())[:3]:
    offer = listing['listing']['offers'][0]
    ex_amt = offer['exchange']['amount']
    chaos_amt = offer['item']['amount']
    print(f"  {ex_amt} ex for {chaos_amt} chaos = {chaos_amt/ex_amt:.2f} chaos/ex")