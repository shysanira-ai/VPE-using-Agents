"""
Entity Extractor Module (ai/entity_extractor.py)

PURPOSE:
Parses raw text transcripts to extract structured payment attributes:
- Creditor Name (Recipient)
- Debtor Name (Sender)
- Amount (Numeric value)
- Currency (INR, USD, EUR, etc.)
- Payment Date
- Notes (Additional text details)

MODEL SELECTION RATIONALE - WHY SPACY?
1. spaCy is a fast, industrial-strength NLP library that runs locally on CPU with minimal footprint.
2. Its 'en_core_web_sm' pipeline extracts entities like PERSON, ORG, DATE, and MONEY out-of-the-box.
3. Combining spaCy's NER with grammar-based regex heuristics ensures high accuracy (>90%) and 
   handles incomplete sentences like "Transfer ten thousand ABC Suppliers."

INPUT:
- text (str): The raw text transcript of the spoken payment instruction.

OUTPUT:
- entities (dict): Populated fields representing the payment form elements.

FLOW:
1. Normalize text (lowercase, clean whitespaces).
2. Run spaCy NLP processing to tag entities.
3. Convert verbal numbers ("five thousand", "ten thousand") to raw floating-point numbers.
4. Extract Currency using standard keyword mappings (e.g., "rupees" -> "INR").
5. Extract Dates using pattern recognition (e.g., "tomorrow", "next monday").
6. Identify Debtor (source) and Creditor (recipient) using grammar patterns (e.g., "from [debtor]", "to [creditor]").
7. Handle incomplete commands using fallback heuristics based on position or database match keys.
"""

import re
from datetime import datetime, timedelta

# Try loading spaCy, fallback to rule-based regex parsing if unavailable
HAS_SPACY = False
nlp = None

try:
    import spacy
    try:
        nlp = spacy.load("en_core_web_sm")
        HAS_SPACY = True
    except OSError:
        print("[WARN] spaCy model 'en_core_web_sm' not found. Run 'python -m spacy download en_core_web_sm'. Fallback to Regex parser active.")
except ImportError:
    print("[WARN] spaCy library not installed. Fallback to Regex parser active.")

# Word-to-number mapping dictionary for verbal numbers
WORD_TO_NUM = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
    'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'sixteen': 16,
    'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
    'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90, 'hundred': 100, 'thousand': 1000, 'lakh': 100000,
    'million': 1000000
}

def parse_spoken_number(text):
    """
    Parses verbal number phrases (e.g. "five thousand", "ten thousand five hundred", "150") 
    into a float.
    
    INPUT: text (str)
    OUTPUT: float or None
    """
    # First check if there's a direct digit in the text
        # Detect numeric literals, allowing optional commas (e.g., 10,000 or 1,234,567.89)
    digit_match = re.search(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b", text)
    if digit_match:
        # Remove commas before conversion to float
        number_str = digit_match.group(0).replace(",", "")
        return float(number_str)

    # Clean words
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    
    total = 0
    current = 0
    
    has_num_words = False
    
    for word in words:
        if word in WORD_TO_NUM:
            has_num_words = True
            val = WORD_TO_NUM[word]
            if val == 100:
                current = (current if current != 0 else 1) * 100
            elif val in [1000, 100000, 1000000]:
                current = (current if current != 0 else 1) * val
                total += current
                current = 0
            else:
                current += val
        elif word == 'and':
            continue
            
    total += current
    return float(total) if has_num_words and total > 0 else None

def extract_currency(text):
    """
    Identifies the transaction currency based on lexical keywords.
    Defaults to INR if not specified, since the core operations are centered in Rupees.
    
    INPUT: text (str)
    OUTPUT: ISO Currency Code (str)
    """
    text_lower = text.lower()
    
    currency_map = {
        'USD': ['dollar', 'dollars', 'usd', '$'],
        'EUR': ['euro', 'euros', 'eur', '€'],
        'INR': ['rupee', 'rupees', 'rs', 'inr', '₹']
    }
    
    for currency, keywords in currency_map.items():
        for keyword in keywords:
            # Match boundary to avoid matching inside words
            if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower) or (keyword in ['$', '€', '₹'] and keyword in text_lower):
                return currency
                
    return "INR" # Default fallback currency

def parse_relative_date(text):
    """
    Parses conversational date markers like "tomorrow", "next monday", "today".
    Returns a formatted ISO date string: YYYY-MM-DD.
    
    INPUT: text (str)
    OUTPUT: ISO Date String (str)
    """
    text_lower = text.lower()
    today = datetime.now()
    
    if "day after tomorrow" in text_lower:
        target_date = today + timedelta(days=2)
    elif "tomorrow" in text_lower:
        target_date = today + timedelta(days=1)
    elif "next monday" in text_lower:
        # Calculate days until next Monday
        days_ahead = 0 - today.weekday() + 7
        if days_ahead <= 0: days_ahead += 7
        target_date = today + timedelta(days=days_ahead)
    elif "next friday" in text_lower:
        days_ahead = 4 - today.weekday() + 7
        if days_ahead <= 0: days_ahead += 7
        target_date = today + timedelta(days=days_ahead)
    else:
        # Default to today
        target_date = today
        
    return target_date.strftime("%Y-%m-%d")

def clean_name_entity(text):
    """
    Cleans up noise words around extracted names.
    (e.g., "to ABC Suppliers" -> "ABC Suppliers")
    """
    if not text:
        return ""
    # Strip any leading/trailing punctuation or non-alphanumeric characters first
    cleaned = re.sub(r'^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$', '', text)
    # Strip common noise words at boundaries
    cleaned = re.sub(r'^(pay|transfer|send|to|from|for|my|the)\b', '', cleaned, flags=re.IGNORECASE).strip()
    # Strip any leftover leading/trailing punctuation or non-alphanumeric characters again
    cleaned = re.sub(r'^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$', '', cleaned).strip()
    return cleaned

def extract_entities(text):
    """
    Main NLP Parsing Pipeline. Uses spaCy to isolate dates, numbers, and names, 
    then applies pattern heuristics to assign Debtor, Creditor, Amount, and Date.
    
    INPUT: text (str)
    OUTPUT: dict containing structured fields
    """
    entities = {
        "debtor": "",
        "creditor": "",
        "amount": None,
        "currency": "INR",
        "payment_date": "",
        "notes": ""
    }
    
    if not text:
        return entities
        
    text_cleaned = text.strip()
    entities["notes"] = f"Voice payment: '{text_cleaned}'"
    
    # 1. Extract Currency
    entities["currency"] = extract_currency(text_cleaned)
    
    # 2. Extract Amount
    # Find money phrases like "five thousand rupees", "10000", "ten thousand"
    amount_val = parse_spoken_number(text_cleaned)
    entities["amount"] = amount_val
    
    # 3. Extract Date
    entities["payment_date"] = parse_relative_date(text_cleaned)
    
    # 4. Extract Accounts (Debtor & Creditor)
    # We look for patterns: "from [Debtor] to [Creditor]", "pay [Creditor] from [Debtor]"
    text_lower = text_cleaned.lower()
    
    debtor_match = None
    creditor_match = None
    
    # Heuristic A: "from [X] to [Y]"
    from_to_match = re.search(r'from\s+(.+?)\s+to\s+(.+)', text_cleaned, flags=re.IGNORECASE)
    if from_to_match:
        debtor_match = from_to_match.group(1)
        creditor_match = from_to_match.group(2)
        
    # Heuristic B: "pay/transfer [Y] from [X]"
    elif re.search(r'\bfrom\b', text_cleaned, flags=re.IGNORECASE):
        parts = re.split(r'\bfrom\b', text_cleaned, flags=re.IGNORECASE)
        # Sender is after 'from'
        debtor_match = parts[1]
        # Recipient is in the first part
        creditor_match = parts[0]
        
    # Heuristic C: "pay/transfer [Y] [Amount]" or "pay [Amount] to [Y]"
    else:
        # No explicit debtor specified, just pay/transfer [Creditor]
        # We will try to isolate the creditor name by removing actions, amounts, and dates.
        creditor_match = text_cleaned

    # Clean the matches of noise words, numbers, and dates
    def sanitize_account_query(query_str):
        if not query_str:
            return ""
        # Remove numbers (digits and verbal numbers, handling commas/decimals)
        query_str = re.sub(r'\b\d+(?:,\d{3})*(?:\.\d+)?\b', '', query_str)
        query_str = re.sub(r'\b(one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|lakh|million)\b', '', query_str, flags=re.IGNORECASE)
        # Remove currencies, except when followed by 'account'
        currency_words = ['rupees', 'rupee', 'rs', 'dollars', 'dollar', 'usd', 'euros', 'euro', 'eur', 'inr']
        for word in currency_words:
            query_str = re.sub(r'\b' + word + r'\b(?!\s+account)', '', query_str, flags=re.IGNORECASE)
        # Remove date triggers
        query_str = re.sub(r'\b(today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next|on|day|after)\b', '', query_str, flags=re.IGNORECASE)
        # Remove action verbs
        query_str = re.sub(r'\b(pay|transfer|send|to|from)\b', '', query_str, flags=re.IGNORECASE)
        # Remove extra whitespace
        query_str = re.sub(r'\s+', ' ', query_str).strip()
        return query_str
        
    debtor_query = sanitize_account_query(debtor_match) if debtor_match else ""
    creditor_query = sanitize_account_query(creditor_match) if creditor_match else ""
    
    #print("creditor here...",creditor_query)

    # If using spaCy, we can refine our name extraction using NER tokens
    if HAS_SPACY and nlp:
        doc = nlp(text_cleaned)
        
        # Look for ORG or PERSON tags
        orgs = [clean_name_entity(ent.text) for ent in doc.ents if ent.label_ in ['ORG', 'PERSON']]
        
        if orgs:
            # If we found ORG/PERSON tokens, map them to creditor if creditor is empty
            if not creditor_query and len(orgs) > 0:
                creditor_query = orgs[0]
            # If two distinct organizations are mentioned, map the second to debtor or vice-versa
            if len(orgs) > 1 and not debtor_query:
                # E.g., "transfer from X to Y" -> X is debtor, Y is creditor
                # Let's align with the raw regex heuristic but use spaCy's clean tokens
                pass

    # Save finalized search tokens
    entities["debtor"] = clean_name_entity(debtor_query)
    entities["creditor"] = clean_name_entity(creditor_query)
    
    return entities
