#!/usr/bin/env python3
"""
Database Reset Utility for AI Media Workflow App

This script provides safe ways to reset or clean the jobs database.
Run this script when both Flask app and worker are stopped.

Usage:
    python3 reset_database.py                  # Interactive menu
    python3 reset_database.py --clear-all      # Clear all jobs
    python3 reset_database.py --clear-failed   # Clear only failed jobs
    python3 reset_database.py --clear-stuck    # Clear stuck processing jobs
    python3 reset_database.py --full-reset     # Delete entire database
"""

import os
import sys
import sqlite3
import argparse
from datetime import datetime

DATABASE_PATH = 'jobs.db'

def get_db_connection():
    """Creates a database connection."""
    if not os.path.exists(DATABASE_PATH):
        print(f"❌ Database file '{DATABASE_PATH}' not found.")
        return None
    
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

def get_job_counts():
    """Get counts of jobs by status."""
    try:
        with get_db_connection() as conn:
            if not conn:
                return {}
            
            cursor = conn.cursor()
            counts = {}
            
            # Total count
            result = cursor.execute("SELECT COUNT(*) as count FROM jobs").fetchone()
            counts['total'] = result['count'] if result else 0
            
            # By status
            status_results = cursor.execute("""
                SELECT status, COUNT(*) as count 
                FROM jobs 
                GROUP BY status 
                ORDER BY count DESC
            """).fetchall()
            
            for row in status_results:
                counts[row['status']] = row['count']
                
            return counts
    except Exception as e:
        print(f"❌ Error getting job counts: {e}")
        return {}

def clear_all_jobs():
    """Clear all jobs from database."""
    try:
        with get_db_connection() as conn:
            if not conn:
                return False
                
            cursor = conn.cursor()
            result = cursor.execute("DELETE FROM jobs")
            count = result.rowcount
            conn.commit()
            print(f"✅ Cleared {count} jobs from database.")
            return True
    except Exception as e:
        print(f"❌ Error clearing jobs: {e}")
        return False

def clear_failed_jobs():
    """Clear only failed jobs."""
    try:
        with get_db_connection() as conn:
            if not conn:
                return False
                
            cursor = conn.cursor()
            result = cursor.execute("DELETE FROM jobs WHERE status = 'failed'")
            count = result.rowcount
            conn.commit()
            print(f"✅ Cleared {count} failed jobs from database.")
            return True
    except Exception as e:
        print(f"❌ Error clearing failed jobs: {e}")
        return False

def clear_stuck_jobs():
    """Clear stuck processing jobs."""
    try:
        with get_db_connection() as conn:
            if not conn:
                return False
                
            cursor = conn.cursor()
            result = cursor.execute("DELETE FROM jobs WHERE status IN ('processing', 'keying_processing')")
            count = result.rowcount
            conn.commit()
            print(f"✅ Cleared {count} stuck processing jobs from database.")
            return True
    except Exception as e:
        print(f"❌ Error clearing stuck jobs: {e}")
        return False

def full_reset():
    """Delete the entire database file."""
    try:
        files_to_remove = [DATABASE_PATH, f"{DATABASE_PATH}-shm", f"{DATABASE_PATH}-wal"]
        removed_count = 0
        
        for file_path in files_to_remove:
            if os.path.exists(file_path):
                os.remove(file_path)
                removed_count += 1
                print(f"🗑️ Removed {file_path}")
        
        if removed_count > 0:
            print(f"✅ Full database reset complete. Removed {removed_count} files.")
            print("📝 Database will be recreated automatically when you restart the Flask app.")
        else:
            print("ℹ️ No database files found to remove.")
        return True
    except Exception as e:
        print(f"❌ Error during full reset: {e}")
        return False

def show_status():
    """Show current database status."""
    print("\n📊 Current Database Status:")
    print("=" * 40)
    
    if not os.path.exists(DATABASE_PATH):
        print("❌ Database file not found. Database appears to be empty.")
        return
    
    counts = get_job_counts()
    if not counts:
        print("❌ Could not read database.")
        return
    
    total = counts.get('total', 0)
    if total == 0:
        print("✅ Database is empty (no jobs).")
        return
    
    print(f"Total Jobs: {total}")
    print("\nBy Status:")
    for status, count in counts.items():
        if status != 'total':
            print(f"  {status}: {count}")

def interactive_menu():
    """Show interactive menu for database operations."""
    while True:
        print("\n🔧 AI Media Workflow Database Reset Utility")
        print("=" * 50)
        
        show_status()
        
        print("\nOptions:")
        print("1. Clear all jobs")
        print("2. Clear failed jobs only") 
        print("3. Clear stuck processing jobs only")
        print("4. Full database reset (delete files)")
        print("5. Refresh status")
        print("6. Exit")
        
        choice = input("\nEnter your choice (1-6): ").strip()
        
        if choice == '1':
            if input("\n⚠️ Clear ALL jobs? This cannot be undone! Type 'yes' to confirm: ") == 'yes':
                clear_all_jobs()
            else:
                print("❌ Operation cancelled.")
                
        elif choice == '2':
            if input("\n🧹 Clear all failed jobs? Type 'yes' to confirm: ") == 'yes':
                clear_failed_jobs()
            else:
                print("❌ Operation cancelled.")
                
        elif choice == '3':
            if input("\n🔄 Clear stuck processing jobs? Type 'yes' to confirm: ") == 'yes':
                clear_stuck_jobs()
            else:
                print("❌ Operation cancelled.")
                
        elif choice == '4':
            print("\n⚠️  DANGER: This will completely delete the database!")
            print("The database will be recreated when you restart the Flask app.")
            if input("Type 'DELETE' to confirm: ") == 'DELETE':
                full_reset()
            else:
                print("❌ Operation cancelled.")
                
        elif choice == '5':
            continue  # Will refresh status at top of loop
            
        elif choice == '6':
            print("👋 Goodbye!")
            break
            
        else:
            print("❌ Invalid choice. Please enter 1-6.")

def main():
    parser = argparse.ArgumentParser(description='Reset AI Media Workflow Database')
    parser.add_argument('--clear-all', action='store_true', help='Clear all jobs')
    parser.add_argument('--clear-failed', action='store_true', help='Clear failed jobs only')
    parser.add_argument('--clear-stuck', action='store_true', help='Clear stuck processing jobs')
    parser.add_argument('--full-reset', action='store_true', help='Delete entire database')
    parser.add_argument('--status', action='store_true', help='Show database status only')
    
    args = parser.parse_args()
    
    # Check if Flask app or worker might be running
    print("⚠️  Make sure Flask app and worker are stopped before running this script!")
    print("   (Press Ctrl+C in both terminal windows)")
    
    if not any([args.clear_all, args.clear_failed, args.clear_stuck, args.full_reset, args.status]):
        # No arguments provided, show interactive menu
        interactive_menu()
        return
    
    # Handle command line arguments
    if args.status:
        show_status()
        
    elif args.clear_all:
        print("\n🗑️ Clearing all jobs...")
        clear_all_jobs()
        
    elif args.clear_failed:
        print("\n🧹 Clearing failed jobs...")
        clear_failed_jobs()
        
    elif args.clear_stuck:
        print("\n🔄 Clearing stuck jobs...")
        clear_stuck_jobs()
        
    elif args.full_reset:
        print("\n💥 Performing full database reset...")
        if input("⚠️ This will DELETE the entire database! Type 'DELETE' to confirm: ") == 'DELETE':
            full_reset()
        else:
            print("❌ Operation cancelled.")

if __name__ == "__main__":
    main()
