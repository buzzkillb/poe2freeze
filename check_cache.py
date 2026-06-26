import sqlite3
db = sqlite3.connect(r'C:\Users\travanx\Dropbox\projects\poe2\ninja\prices.db')
cur = db.execute("SELECT key, name, base, chaos_value, divine_value, exalted_value, listing_count, detail_json, datetime(expires_at, 'unixepoch') as exp FROM prices WHERE kind='waystone' ORDER BY expires_at DESC LIMIT 20")
for r in cur.fetchall():
    detail = r[7] or ''
    print(f"  {r[2]:30} mods={r[3]:.0f}c div={r[4]:.0f} listing={r[6]} exp={r[8]} detail={detail[:80]}")
print()
print('Total waystone cache entries:', db.execute("SELECT COUNT(*) FROM prices WHERE kind='waystone'").fetchone()[0])