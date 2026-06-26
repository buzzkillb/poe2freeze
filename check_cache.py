import sqlite3
db = sqlite3.connect(r'C:\Users\travanx\Dropbox\projects\poe2\ninja\prices.db')
for row in db.execute("SELECT key, name, chaos_value, divine_value, exalted_value, listing_count, detail_json FROM prices WHERE kind='waystone' ORDER BY rowid DESC LIMIT 10"):
    print(row)