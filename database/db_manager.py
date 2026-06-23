"""
Database Manager Module (database/db_manager.py)

PURPOSE:
This module manages the SQLite relational database for the Voice-Based Payment system.
It stores client account records (balances, currency, types) and payment drafts.
It handles database initialization, table creation, initial data seeding, 
balance verification, and CRUD operations for drafts and accounts.

FLOW:
1. When imported or initialized, it opens a connection to `voice_payment.db`.
2. Checks if tables exist; if not, creates 'accounts' and 'drafts' tables.
3. Seeds default debtor and creditor accounts for demo/testing purposes if the db is empty.
4. Exposes API functions to query accounts, save payment drafts, verify balances, and submit payments.

INPUTS & OUTPUTS:
- Inputs: Varies by database query (e.g., account numbers, amounts, draft details).
- Outputs: Dicts/lists representing accounts or drafts, boolean flags, or error messages.
"""

import sqlite3
import os
import json
from datetime import datetime

# Define database file path inside the workspace database directory
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_payment.db")

def get_connection():
    """
    Establishes and returns a connection to the SQLite database.
    Configured to return Row objects for dictionary-like access to columns.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    Initializes the database. Creates tables if they do not exist and seeds initial records.
    
    TABLES:
    1. accounts: Represents customer bank accounts (sender/debtor & receiver/creditor).
    2. drafts: Stores voice-extracted or manually edited payment draft requests.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Create Accounts Table
    # Stores name, account number, balance, type, currency, and country for validation.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            account_number TEXT PRIMARY KEY,
            account_holder TEXT NOT NULL,
            balance REAL NOT NULL,
            account_type TEXT NOT NULL,
            currency TEXT NOT NULL,
            country TEXT NOT NULL
        )
    """)

    # Create Drafts Table
    # Stores extracted drafts. References debtor and creditor accounts.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debtor_account TEXT,
            creditor_account TEXT,
            amount REAL,
            currency TEXT,
            payment_date TEXT,
            category TEXT,
            notes TEXT,
            status TEXT DEFAULT 'Draft',
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    
    # Check if accounts table is empty, and seed with default values if so.
    cursor.execute("SELECT COUNT(*) FROM accounts")
    if cursor.fetchone()[0] == 0:
        seed_database(conn)
        
    conn.close()

def seed_database(conn):
    """
    Seeds the SQLite database with realistic mock bank accounts.
    Includes current and savings accounts for both the user (debtor) and vendors (creditors).
    
    INPUTS: sqlite3.Connection
    OUTPUTS: None (inserts records into the DB)
    """
    cursor = conn.cursor()
    
    # Mock Accounts Data
    # Setup standard debtor accounts (user accounts) and creditor accounts (recipients)
    # Includes different currencies to test Multi-Currency classification
    accounts = [
        # Debtor accounts (User accounts)
        ("11223344", "San Shy Current Account", 15000.0, "Current", "INR", "India"),
        ("55667788", "San Shy Savings Account", 4500.0, "Savings", "INR", "India"),
        ("99001122", "San Shy USD Account", 2500.0, "Savings", "USD", "India"),
        
        # Creditor accounts (Recipients / Vendors)
        ("12345678", "ABC Suppliers Ltd", 0.0, "Current", "INR", "India"),
        ("87654321", "Global Logistics Corp", 0.0, "Current", "USD", "USA"),
        ("11112222", "Tech Solutions Germany", 0.0, "Current", "EUR", "Germany"),
        ("33334444", "Charlie Local Groceries", 0.0, "Savings", "INR", "India")
    ]
    
    cursor.executemany("""
        INSERT INTO accounts (account_number, account_holder, balance, account_type, currency, country)
        VALUES (?, ?, ?, ?, ?, ?)
    """, accounts)
    
    conn.commit()
    print("Database seeded successfully with initial accounts.")

def get_all_accounts():
    """
    Fetches all accounts from the database.
    Useful for populating account drop-downs on the frontend.
    
    OUTPUT: List of dicts representing each account
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM accounts")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_account(account_number):
    """
    Fetches details of a specific account by account number.
    
    INPUT: account_number (str)
    OUTPUT: Dict representing the account, or None if not found
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM accounts WHERE account_number = ?", (account_number,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_account_by_name(holder_name):
    """
    Performs a case-insensitive search for an account using the holder name.
    
    INPUT: holder_name (str)
    OUTPUT: Dict representing the account, or None if not found
    """
    conn = get_connection()
    cursor = conn.cursor()
    # Use LIKE for partial matches
    cursor.execute("SELECT * FROM accounts WHERE account_holder LIKE ? LIMIT 1", (f"%{holder_name}%",))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def save_payment_draft(draft_data):
    """
    Saves a payment draft. If draft_id is provided, it updates the existing draft;
    otherwise, it inserts a new payment draft.
    
    INPUT: draft_data (dict) containing fields like debtor_account, creditor_account,
           amount, currency, payment_date, category, notes, and optional id.
    OUTPUT: Saved/Updated draft record dict with its ID.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    draft_id = draft_data.get("id")
    debtor = draft_data.get("debtor_account")
    creditor = draft_data.get("creditor_account")
    amount = draft_data.get("amount")
    currency = draft_data.get("currency")
    payment_date = draft_data.get("payment_date")
    category = draft_data.get("category")
    notes = draft_data.get("notes")
    status = draft_data.get("status", "Draft")
    now_str = datetime.now().isoformat()
    
    if draft_id:
        # Update existing draft
        cursor.execute("""
            UPDATE drafts 
            SET debtor_account = ?, creditor_account = ?, amount = ?, currency = ?, 
                payment_date = ?, category = ?, notes = ?, status = ?
            WHERE id = ?
        """, (debtor, creditor, amount, currency, payment_date, category, notes, status, draft_id))
    else:
        # Create new draft
        cursor.execute("""
            INSERT INTO drafts (debtor_account, creditor_account, amount, currency, payment_date, category, notes, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (debtor, creditor, amount, currency, payment_date, category, notes, status, now_str))
        draft_id = cursor.lastrowid
        
    conn.commit()
    
    # Retrieve and return the updated/created draft
    cursor.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_drafts():
    """
    Fetches all drafts sorted by creation time descending.
    
    OUTPUT: List of dicts representing payment drafts
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drafts ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def execute_payment(draft_id):
    """
    Submits a payment. Validates details, checks debtor account balance, 
    and updates balances in a secure database transaction if valid.
    
    INPUT: draft_id (int)
    OUTPUT: (Success status (bool), Status Message (str))
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Fetch the draft
        cursor.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,))
        draft = cursor.fetchone()
        if not draft:
            return False, "Payment draft not found."
            
        if draft["status"] == "Submitted":
            return False, "This payment has already been completed."
            
        debtor_num = draft["debtor_account"]
        creditor_num = draft["creditor_account"]
        amount = draft["amount"]
        
        # Basic validation: are account fields populated?
        if not debtor_num or not creditor_num or not amount or amount <= 0:
            return False, "Payment fields are incomplete or invalid."
            
        # Retrieve Debtor Account and verify balance
        cursor.execute("SELECT * FROM accounts WHERE account_number = ?", (debtor_num,))
        debtor = cursor.fetchone()
        if not debtor:
            return False, "Debtor (sender) account does not exist."
            
        # Verify Creditor Account exists
        cursor.execute("SELECT * FROM accounts WHERE account_number = ?", (creditor_num,))
        creditor = cursor.fetchone()
        if not creditor:
            return False, "Creditor (receiver) account does not exist."
            
        # Validate balance (must be >= amount)
        if debtor["balance"] < amount:
            return False, f"Insufficient balance. Account balance is {debtor['balance']} {debtor['currency']}, transaction requires {amount} {draft['currency']}."
            
        # Begin transaction updates
        # Deduct from debtor
        cursor.execute("""
            UPDATE accounts 
            SET balance = balance - ? 
            WHERE account_number = ?
        """, (amount, debtor_num))
        
        # Credit receiver
        cursor.execute("""
            UPDATE accounts 
            SET balance = balance + ? 
            WHERE account_number = ?
        """, (amount, creditor_num))
        
        # Update draft status
        cursor.execute("""
            UPDATE drafts 
            SET status = 'Submitted' 
            WHERE id = ?
        """, (draft_id,))
        
        conn.commit()
        return True, "Payment successfully processed and balance updated."
        
    except Exception as e:
        conn.rollback()
        return False, f"Transaction error occurred: {str(e)}"
    finally:
        conn.close()

# Automatic setup on import
init_db()
