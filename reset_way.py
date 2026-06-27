"""Test remaining rate limit status and fix the waystone pricer to handle 429 properly."""
import sqlite3
db = sqlite3.connect(r'C:\Users\travanx\Dropbox\projects\poe2\ninja\prices.db')
db.execute("DELETE FROM prices WHERE kind='waystone'")
db.commit()
print("Waystone cache cleared")
print("Rate limit should clear in ~60s from last test")