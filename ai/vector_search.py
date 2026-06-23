"""
Vector Search Module (ai/vector_search.py)

PURPOSE:
Implements semantic lookup for sender (debtor) and recipient (creditor) accounts using ChromaDB.
When a user says "ABC Suppliers" or "my savings", NLP extracts the text, and this module 
performs a vector search (RAG) to map the spoken phrase to the exact record inside the bank database.

MODEL SELECTION RATIONALE - WHY CHROMADB?
1. ChromaDB is a fast, developer-friendly, open-source vector database that runs entirely in-memory or locally.
2. It has zero external server dependencies, making it perfect for lightweight offline local applications.
3. It integrates seamlessly with Python, allowing us to implement RAG out-of-the-box.

RAG (RETRIEVAL-AUGMENTED GENERATION) RATIONALE:
RAG is chosen here because bank account directories can be large and dynamically updated.
Rather than training a model to recognize every account name, we extract entities using NER,
and use Vector Embeddings to search the database of accounts. This enables handling abbreviations, 
spelling differences, and typos (e.g. "ABC" -> "ABC Suppliers Ltd").

INPUTS:
- query_text (str): Spoken or extracted name (e.g. "ABC Suppliers", "Savings account")
- limit (int): Number of top matches to return

OUTPUTS:
- account_dict (dict): The best matching account record containing name, number, balance, currency, etc.

FLOW:
1. Initialize ChromaDB persistent client.
2. Create/Get the collection 'bank_accounts'.
3. Sync SQLite account records with the ChromaDB collection (using holder name as document text).
4. Perform semantic search using cosine similarity embeddings.
5. Fallback to fuzzy string matching (difflib) if ChromaDB fails to load or import.
"""

import os
import sys
import difflib
from database.db_manager import get_all_accounts

# Flags for tracking ChromaDB availability
HAS_CHROMADB = False
chroma_client = None
collection = None

try:
    import chromadb
    from chromadb.config import Settings
    HAS_CHROMADB = True
except ImportError:
    print("[WARN] ChromaDB is not installed. Falling back to difflib fuzzy search.")
    HAS_CHROMADB = False

# Path for persistent vector storage
CHROMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database", "chroma_db")

def init_vector_db():
    """
    Initializes ChromaDB, creates the account names collection,
    and seeds it with current records from the SQLite database.
    Includes robust handling for corrupted persistent stores.
    """
    global chroma_client, collection
    if not HAS_CHROMADB:
        return
    
    try:
        # Create in-memory client (no persistent SQLite storage) to avoid schema issues
        chroma_client = chromadb.Client()
        # Get or create collection in-memory
        collection = chroma_client.get_or_create_collection(
            name="bank_accounts",
            metadata={"hnsw:space": "cosine"}
        )
        # Sync database records
        sync_accounts_to_vector_db()
    except Exception as e:
        # If initialization fails (e.g., corrupted directory), fallback to in‑memory client
        print(f"[WARN] ChromaDB init error: {e}. Using in-memory fallback.")
        chroma_client = chromadb.Client()
        collection = None
        return

def sync_accounts_to_vector_db():
    """
    Fetches all accounts from SQLite database and indexes them in ChromaDB.
    Clears existing collection items to ensure clean synchronization.
    """
    global collection
    if collection is None:
        return
        
    accounts = get_all_accounts()
    if not accounts:
        return
        
    # Prepare data for vectors
    ids = []
    documents = []
    metadatas = []
    
    for account in accounts:
        # Document is the name we want to match semantically (e.g. "San Shy Savings Account")
        documents.append(account["account_holder"])
        # ID is the account number (unique key)
        ids.append(account["account_number"])
        # Store full account metadata
        metadatas.append({
            "account_number": account["account_number"],
            "currency": account["currency"],
            "country": account["country"],
            "account_type": account["account_type"]
        })
        
    if ids:
        # Delete old items to prevent duplication
        try:
            existing = collection.get()
            if existing and existing['ids']:
                collection.delete(ids=existing['ids'])
        except Exception:
            pass
            
        # Upsert documents and their metadata
        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )
        print(f"Indexed {len(ids)} bank accounts in ChromaDB vector storage.")

def search_account_vector(query_text, limit=1):
    """
    Searches ChromaDB for the closest matching account name.
    
    INPUT: query_text (str)
    OUTPUT: Dict containing account details or None
    """
    global collection
    if collection is None or not query_text:
        return None
        
    try:
        results = collection.query(
            query_texts=[query_text],
            n_results=limit
        )
        
        if results and results['ids'] and len(results['ids'][0]) > 0:
            best_id = results['ids'][0][0]
            # Fetch full details from database to get fresh balance
            from database.db_manager import get_account
            return get_account(best_id)
            
    except Exception as e:
        print(f"[WARN] ChromaDB query error: {e}. Trying database fallback.")
    return None

def search_account_fallback(query_text):
    """
    Fuzzy string matching fallback using difflib.
    Runs if ChromaDB is not installed or encounters runtime errors.
    
    INPUT: query_text (str)
    OUTPUT: Dict containing account details or None
    """
    if not query_text:
        return None
        
    accounts = get_all_accounts()
    best_match = None
    highest_ratio = 0.0
    
    query_lower = query_text.lower()
    
    for account in accounts:
        name_lower = account["account_holder"].lower()
        # Compute matching ratio (0.0 to 1.0)
        ratio = difflib.SequenceMatcher(None, query_lower, name_lower).ratio()
        
        # Boost ratio if query is a direct substring of name (e.g. "ABC" inside "ABC Suppliers Ltd")
        if query_lower in name_lower:
            ratio += 0.3
            
        if ratio > highest_ratio and ratio > 0.4:  # 0.4 minimum similarity threshold
            highest_ratio = ratio
            best_match = account
            
    return best_match

def search_account(query_text):
    """
    Unified search function that uses ChromaDB Vector Search 
    and automatically falls back to fuzzy string matching.
    
    INPUT: query_text (str)
    OUTPUT: Account dict or None
    """
    if not query_text:
        return None
        
    # Attempt Vector DB search
    if HAS_CHROMADB and collection is not None:
        match = search_account_vector(query_text)
        if match:
            return match
            
    # Fallback search
    return search_account_fallback(query_text)

# Ensure any open vector client is closed before exiting or resetting
def close_vector_db():
    global chroma_client, collection
    chroma_client = None
    collection = None

# Initialize vector database on module import
init_vector_db()
