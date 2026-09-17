# fix_db.py - Run this once to fix your database
import sqlite3
import os

DB_PATH = "database/events.db"

def fix_database():
    """Fix database schema issues"""
    if not os.path.exists("database"):
        os.makedirs("database")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("Fixing database schema...")
    
    # First, check what tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print("Existing tables:", tables)
    
    # Drop and recreate user_settings table with correct schema
    cursor.execute("DROP TABLE IF EXISTS user_settings")
    
    # Create correct user_settings table
    cursor.execute('''
        CREATE TABLE user_settings (
            user_id INTEGER PRIMARY KEY,
            alert_threshold INTEGER DEFAULT 3,
            email_notifications BOOLEAN DEFAULT 1,
            recipient_email TEXT,
            pet_name TEXT,
            pet_type TEXT DEFAULT 'dog',
            pet_age INTEGER,
            daily_report BOOLEAN DEFAULT 0,
            weekly_report BOOLEAN DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Check if users table exists and has default user
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if cursor.fetchone():
        cursor.execute("SELECT COUNT(*) FROM users WHERE username='admin'")
        if cursor.fetchone()[0] == 0:
            import hashlib
            admin_hash = hashlib.sha256("petstress123".encode()).hexdigest()
            cursor.execute('''
                INSERT INTO users (username, password_hash, email) 
                VALUES (?, ?, ?)
            ''', ("admin", admin_hash, "admin@petstress.com"))
    
    conn.commit()
    conn.close()
    print("Database fixed successfully!")

if __name__ == "__main__":
    fix_database()