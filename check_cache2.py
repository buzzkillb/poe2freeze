import sqlite3
db = sqlite3.connect(r'C:\Users\travanx\Dropbox\projects\poe2\ninja\prices.db')
cur = db.execute("SELECT key, name, chaos_value, divine_value, exalted_value, listing_count, detail_json, datetime(expires_at, 'unixepoch') as exp FROM prices WHERE kind='waystone'")
for r in cur.fetchall():
    detail = r[6] or ''
    print(f"  {r[1]:30} c={r[2]:.0f} d={r[3]:.0f} x={r[4]:.0f} n={r[5]} exp={r[7]} {detail[:80]}")
print()
print('Total waystone entries:', db.execute("SELECT COUNT(*) FROM prices WHERE kind='waystone'").fetchone()[0])