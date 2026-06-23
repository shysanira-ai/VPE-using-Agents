"""
Payment Classifier Module (ai/classifier.py)

PURPOSE:
Automatically classifies payment transactions into core regulatory categories:
- Domestic Payment (Sender and receiver accounts are in the same country, same currency)
- International Payment (Sender and receiver are in different countries, but share currency)
- Multi-Currency Payment (Transaction currency differs from either debtor or creditor account currency)

It also classifies the text description to determine the business purpose 
(e.g., 'Vendor/Supplier Payment', 'Utility/Bills', 'Personal Transfer', 'Groceries').

MODEL SELECTION RATIONALE - WHY TRANSFORMER CLASSIFIER / NLP CLASSIFIER?
1. In high-volume banking systems, deep learning text classifiers (like BERT/DistilBERT transformers 
   or spaCy's TextCategorizer) are deployed to read invoice descriptions or memo notes and auto-tag categories.
2. This automates tax tagging, fraud detection, and regulatory reporting.
3. For this lightweight application, we implement:
   - A metadata-driven rule engine for transaction type (Domestic, International, Multi-Currency) 
     using database entity country/currency attributes.
   - An NLP classifier that analyzes keywords and grammar patterns to categorize the *purpose* 
     of the payment (Vendor, Utility, Grocery, General Transfer), simulating a trained model.

INPUTS:
- debtor_account (dict): Sender account details.
- creditor_account (dict): Recipient account details.
- transaction_currency (str): Currency of the payment draft.
- raw_text (str): Spoken description.

OUTPUT:
- category (str): Domestic, International, or Multi-Currency.
- purpose (str): Business category tag (e.g., "Vendor Payment", "Bills & Utilities").
"""

import re

# Categories mapping
CATEGORY_DOMESTIC = "Domestic Payment"
CATEGORY_INTERNATIONAL = "International Payment"
CATEGORY_MULTI_CURRENCY = "Multi-Currency Payment"

def classify_payment_type(debtor, creditor, tx_currency):
    """
    Classifies payment type based on geographic and monetary metadata.
    
    INPUT:
    - debtor (dict): debtor account row
    - creditor (dict): creditor account row
    - tx_currency (str): payment currency code (e.g. 'INR', 'USD')
    
    OUTPUT:
    - String representing category: 'Domestic Payment', 'International Payment', or 'Multi-Currency Payment'
    
    FLOW:
    1. Check if debtor or creditor are missing; if so, default to Domestic.
    2. Check if the payment currency is different from debtor account currency or creditor account currency. 
       If so, classify as Multi-Currency.
    3. If currencies match, check countries. If countries differ, classify as International.
    4. If both countries and currencies match, classify as Domestic.
    """
    if not debtor or not creditor:
        return CATEGORY_DOMESTIC # Default fallback
        
    debtor_country = debtor.get("country", "").upper()
    creditor_country = creditor.get("country", "").upper()
    debtor_currency = debtor.get("currency", "").upper()
    creditor_currency = creditor.get("currency", "").upper()
    tx_currency = tx_currency.upper()
    
    # 1. Multi-Currency Check
    # If the payment currency is different from the sender's account currency,
    # or different from the receiver's account currency, FX conversion is required.
    if tx_currency != debtor_currency or tx_currency != creditor_currency:
        return CATEGORY_MULTI_CURRENCY
        
    # 2. International Check
    # Same currency (e.g., USD to USD) but different countries (e.g., India to USA)
    if debtor_country != creditor_country:
        return CATEGORY_INTERNATIONAL
        
    # 3. Domestic Check
    # Same country and same currency (e.g., India to India, INR)
    return CATEGORY_DOMESTIC

def classify_payment_purpose(text):
    """
    Analyzes the payment transcript to classify the purpose of the transaction.
    Simulates a text classification transformer model by scanning lexical tokens.
    
    INPUT: text (str)
    OUTPUT: Business category tag (str)
    """
    if not text:
        return "General Transfer"
        
    text_lower = text.lower()
    
    # Classification rules (Mapping patterns to categories)
    rules = {
        "Supplier / Vendor Payment": [
            r'\bsuppliers?\b', r'\bvendor\b', r'\bcorp\b', r'\bltd\b', r'\binc\b', 
            r'\bco\b', r'\bsolutions\b', r'\blogistics\b', r'\bpayment for invoice\b'
        ],
        "Utilities & Bills": [
            r'\bbills?\b', r'\belectricity\b', r'\bwater\b', r'\brent\b', r'\binternet\b', 
            r'\bphone\b', r'\bmobile\b', r'\brecharge\b', r'\btaxes?\b'
        ],
        "Groceries & Shopping": [
            r'\bgroceries\b', r'\bgrocery\b', r'\bshop\b', r'\bstore\b', r'\bsupermarket\b', 
            r'\bfood\b', r'\bmarket\b'
        ],
        "Personal Transfer": [
            r'\bfamily\b', r'\bfriend\b', r'\bmom\b', r'\bdad\b', r'\bwife\b', r'\bhusband\b', 
            r'\bson\b', r'\bdaughter\b', r'\bgift\b', r'\bsaving\b'
        ]
    }
    
    for category, patterns in rules.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return category
                
    return "General Transfer" # Default classification category
