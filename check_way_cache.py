import sqlite3
db = sqlite3.connect(r'C:\Users\travanx\Dropbox\projects\poe2\ninja\prices.db')
db.row_factory = sqlite3.Row
print('All waystone cache entries:')
for row in db.execute("SELECT key, base, name, chaos_value, divine_value, exalted_value, listing_count FROM prices WHERE kind='waystone' ORDER BY name"):
    print(f"  {row['name']:35} c={row['chaos_value']:>10} d={row['divine_value']:>10} x={row['exalted_value']:>10} n={row['listing_count']}")