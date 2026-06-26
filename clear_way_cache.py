import sqlite3
db = sqlite3.connect(r'C:\Users\travanx\Dropbox\projects\poe2\ninja\prices.db')
cur = db.execute("SELECT key, kind, name FROM prices WHERE kind='waystone'")
for row in cur.fetchall():
    print(f"  {row[0]} | {row[1]} | {row[2]}")
print()
print(f"Total: {db.execute('SELECT COUNT(*) FROM prices WHERE kind=\"waystone\"').fetchone()[0]}")
if db.execute("SELECT COUNT(*) FROM prices WHERE kind='waystone'").fetchone()[0] > 0:
    db.execute("DELETE FROM prices WHERE kind='waystone'")
    db.commit()
    print("DELETED all waystone cache entries")