"""
Voice-Based Payment Entry (VPE) Test Suite (test_suite.py)

PURPOSE:
This test suite validates individual AI/NLP components (Model & Evaluation Testing)
and the full payment execution flow (End-to-End Scenario Testing) using the Python
built-in `unittest` library.

DESIGN RATIONALE:
1. Zero Dependency: Avoids requiring third-party testing packages or external API credentials.
2. Data Isolation: Uses temporary database and vector store paths to ensure local development 
   and production data are never mutated during test execution.
3. Component Separation: Distinguishes between heuristic/AI behavior and relational transaction states.

HOW TO RUN:
Run all tests:
    python -m unittest test_suite.py
Or run as a script directly:
    python test_suite.py
"""

import os
import sys
import unittest
import shutil
import sqlite3
from datetime import datetime, timedelta

# Append project root directory to path to locate modular files correctly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Define isolated test file paths to prevent overwriting production databases
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DB_PATH = os.path.join(TEST_DIR, "database", "voice_payment_test.db")
TEST_CHROMA_DIR = os.path.join(TEST_DIR, "database", "chroma_db_test")

# PATCH global variables in database and AI modules BEFORE they execute default initializations
import database.db_manager
database.db_manager.DB_PATH = TEST_DB_PATH

import ai.vector_search
ai.vector_search.CHROMA_DIR = TEST_CHROMA_DIR

# Import application components
from database.db_manager import (
    init_db,
    get_account,
    get_all_accounts,
    save_payment_draft,
    execute_payment,
    get_connection
)
from ai.entity_extractor import (
    parse_spoken_number,
    extract_currency,
    parse_relative_date,
    extract_entities
)
from ai.classifier import (
    classify_payment_type,
    classify_payment_purpose
)
from ai.vector_search import (
    init_vector_db,
    search_account,
    sync_accounts_to_vector_db,
    search_account_fallback
)
from ai.agent_orchestrator import VoicePaymentAgentOrchestrator


class TestVoicePaymentSystem(unittest.TestCase):
    """
    Test suite comprising both AI Component tests and End-to-End business scenario tests.
    """

    @classmethod
    def setUpClass(cls):
        """
        Runs once before the entire test suite. Sets up isolated databases.
        """
        # Ensure previous cleanups succeeded
        cls.cleanup_files()
        
        # Initialize SQLite test database and seed records
        init_db()
        
        # Initialize ChromaDB vector database using the patched test folder path
        init_vector_db()
        
        # Instantiate orchestrator
        cls.orchestrator = VoicePaymentAgentOrchestrator()

    @classmethod
    def tearDownClass(cls):
        """
        Runs once after all test cases complete. Performs directory cleanup.
        """
        cls.cleanup_files()

    @classmethod
    def cleanup_files(cls):
        """
        Utility method to delete temporary SQLite and ChromaDB files.
        """
        # Delete the test database file if it exists
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception as e:
                print(f"[WARN] Failed to delete test DB file: {e}")

        # Delete the test vector database directory if it exists
        if os.path.exists(TEST_CHROMA_DIR):
            try:
                # Wait briefly or retry to prevent lock issues on Windows
                shutil.rmtree(TEST_CHROMA_DIR)
            except Exception as e:
                print(f"[WARN] Failed to delete test Chroma DB directory: {e}")

    def setUp(self):
        """
        Runs before every individual test. Ensures a clean transaction slate.
        Re-seeds or resets account balances so tests don't interfere with each other.
        """
        conn = get_connection()
        cursor = conn.cursor()
        
        # Reset balances to default values
        cursor.execute("UPDATE accounts SET balance = 15000.0 WHERE account_number = '11223344'")
        cursor.execute("UPDATE accounts SET balance = 4500.0 WHERE account_number = '55667788'")
        cursor.execute("UPDATE accounts SET balance = 2500.0 WHERE account_number = '99001122'")
        cursor.execute("UPDATE accounts SET balance = 0.0 WHERE account_number = '12345678'")
        cursor.execute("UPDATE accounts SET balance = 0.0 WHERE account_number = '87654321'")
        cursor.execute("UPDATE accounts SET balance = 0.0 WHERE account_number = '11112222'")
        cursor.execute("UPDATE accounts SET balance = 0.0 WHERE account_number = '33334444'")
        
        # Delete any drafts created during previous test cases
        cursor.execute("DELETE FROM drafts")
        conn.commit()
        conn.close()

    # =========================================================================
    # PART 1: AI, MODEL TESTING, AND EVALUATION
    # =========================================================================

    def test_parse_spoken_number(self):
        """
        Test Case 1: Verbal Number Parsing Accuracy (AI/Model Evaluation)
        Ensures spoken/verbal quantities are correctly parsed into floating point values.
        """
        # Test basic digit strings
        self.assertEqual(parse_spoken_number("150"), 150.0)
        self.assertEqual(parse_spoken_number("25.5"), 25.5)

        # Test composite verbal numbers
        self.assertEqual(parse_spoken_number("five thousand"), 5000.0)
        self.assertEqual(parse_spoken_number("ten thousand five hundred"), 10500.0)
        self.assertEqual(parse_spoken_number("three hundred rupees"), 300.0)
        
        # Test large scale integers
        self.assertEqual(parse_spoken_number("one million"), 1000000.0)

        # Test cases with non-number contents (should yield None or evaluate only the numbers)
        self.assertIsNone(parse_spoken_number("pay ABC Suppliers"))

    def test_extract_currency(self):
        """
        Test Case 2: Currency Lexical Extraction Accuracy (AI/Model Evaluation)
        Ensures appropriate currency codes are identified based on keywords.
        """
        # Verify standard keywords map to standard ISO codes
        self.assertEqual(extract_currency("Pay five thousand rupees to ABC"), "INR")
        self.assertEqual(extract_currency("Transfer 500 dollars to John"), "USD")
        self.assertEqual(extract_currency("Send 300 euros to Tech Solutions"), "EUR")
        
        # Verify symbol identification
        self.assertEqual(extract_currency("Send $500 to USA"), "USD")
        self.assertEqual(extract_currency("Give €120 to Germany"), "EUR")
        
        # Verify default fallback currency
        self.assertEqual(extract_currency("Pay ten thousand to ABC Suppliers"), "INR")

    def test_parse_relative_date(self):
        """
        Test Case 3: Relative Date Processing (AI/Model Evaluation)
        Ensures dynamic temporal expressions resolve to correct future ISO strings.
        """
        today = datetime.now()
        
        # Test tomorrow resolution
        tomorrow_expected = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertEqual(parse_relative_date("Pay ABC tomorrow"), tomorrow_expected)

        # Test day after tomorrow resolution
        day_after_expected = (today + timedelta(days=2)).strftime("%Y-%m-%d")
        self.assertEqual(parse_relative_date("Transfer funds day after tomorrow"), day_after_expected)

        # Test default/today resolution
        today_expected = today.strftime("%Y-%m-%d")
        self.assertEqual(parse_relative_date("Transfer today"), today_expected)

    def test_search_account(self):
        """
        Test Case 4: RAG Semantic Account Search and Mapping (AI/Model Evaluation)
        Ensures spoken/fuzzy account queries map to exact SQLite record entries.
        """
        # Test exact retrieval from seeds
        acc_abc = search_account("ABC Suppliers Ltd")
        self.assertIsNotNone(acc_abc)
        self.assertEqual(acc_abc["account_number"], "12345678")

        # Test semantic/fuzzy extraction with abbreviations and typos
        acc_abc_fuzzy = search_account("ABC Suppliers")
        self.assertIsNotNone(acc_abc_fuzzy)
        self.assertEqual(acc_abc_fuzzy["account_number"], "12345678")

        acc_savings = search_account("savings")
        self.assertIsNotNone(acc_savings)
        self.assertEqual(acc_savings["account_number"], "55667788")

        # Test invalid name search on fuzzy string matching fallback.
        # Since fallback has a strict similarity threshold (0.4), completely unrelated queries return None.
        acc_none = search_account_fallback("Nonexistent Vendor LLC")
        self.assertIsNone(acc_none)

    def test_classify_payment_type_and_purpose(self):
        """
        Test Case 5: Payment Classification & Business Intent (AI/Model Evaluation)
        Ensures the categorizer separates domestic, international, and cross-currency FX transactions
        while mapping payment text to business category goals.
        """
        # Setup mock account configurations
        debtor_inr = {"country": "India", "currency": "INR"}
        creditor_inr = {"country": "India", "currency": "INR"}
        debtor_usd = {"country": "India", "currency": "USD"}
        creditor_usd = {"country": "USA", "currency": "USD"}
        creditor_eur = {"country": "Germany", "currency": "EUR"}

        # 1. Test regulatory categories
        # Same country, same currency -> Domestic
        self.assertEqual(classify_payment_type(debtor_inr, creditor_inr, "INR"), "Domestic Payment")
        # Different country, same currency -> International
        self.assertEqual(classify_payment_type(debtor_usd, creditor_usd, "USD"), "International Payment")
        # Diff currency than debtor/creditor -> Multi-Currency Payment
        self.assertEqual(classify_payment_type(debtor_inr, creditor_eur, "EUR"), "Multi-Currency Payment")

        # 2. Test business purpose heuristics
        self.assertEqual(classify_payment_purpose("Payment for invoice to ABC Suppliers"), "Supplier / Vendor Payment")
        self.assertEqual(classify_payment_purpose("Electricity bill recharge"), "Utilities & Bills")
        self.assertEqual(classify_payment_purpose("Buying groceries and fresh food"), "Groceries & Shopping")
        self.assertEqual(classify_payment_purpose("Send a birthday gift to my dad"), "Personal Transfer")
        self.assertEqual(classify_payment_purpose("Random text instruction"), "General Transfer")

    # =========================================================================
    # PART 2: END-TO-END SCENARIO TESTING
    # =========================================================================

    def test_e2e_successful_payment(self):
        """
        Test Case 6: Successful Voice-Based Payment Execution E2E
        Scenario: User requests to pay a valid recipient with sufficient funds.
        Flow: Input -> Orchestrator pipeline -> Save Draft -> Execute Payment -> Check Balance changes.
        """
        spoken_command = "Pay ABC Suppliers 1000 rupees tomorrow from my current account."
        
        # 1. Pipe instruction through the AI Multi-Agent pipeline
        state = self.orchestrator.run_text_pipeline(spoken_command)
        
        # Assert AI correctly extracted parameters
        self.assertTrue(state["validation_results"]["is_valid"])
        self.assertEqual(state["amount"], 1000.0)
        self.assertEqual(state["currency"], "INR")
        self.assertEqual(state["debtor_account"]["account_number"], "11223344")
        self.assertEqual(state["creditor_account"]["account_number"], "12345678")
        
        # 2. Save the extracted details as a payment draft in SQLite
        draft_payload = {
            "debtor_account": state["debtor_account"]["account_number"],
            "creditor_account": state["creditor_account"]["account_number"],
            "amount": state["amount"],
            "currency": state["currency"],
            "payment_date": state["payment_date"],
            "category": state["category"],
            "notes": state["purpose"],
            "status": "Draft"
        }
        saved_draft = save_payment_draft(draft_payload)
        self.assertIsNotNone(saved_draft)
        self.assertEqual(saved_draft["status"], "Draft")
        
        # 3. Submit and execute the payment draft
        success, message = execute_payment(saved_draft["id"])
        
        # Assert database updates succeeded
        self.assertTrue(success)
        self.assertIn("successfully processed", message.lower())
        
        # 4. Verify balances reflect the transaction
        debtor_updated = get_account("11223344")
        creditor_updated = get_account("12345678")
        
        # Debtor should be decremented: 15000.0 - 1000.0 = 14000.0
        self.assertEqual(debtor_updated["balance"], 14000.0)
        # Creditor should be incremented: 0.0 + 1000.0 = 1000.0
        self.assertEqual(creditor_updated["balance"], 1000.0)

    def test_e2e_insufficient_funds(self):
        """
        Test Case 7: Insufficient Funds Guard Scenario E2E
        Scenario: User requests to pay an amount exceeding their debtor account balance.
        Flow: Input -> Pipeline -> Validation flags error -> Execute returns False -> Balances unchanged.
        """
        # Current account balance is 15,000 INR. Requesting 20,000 INR.
        spoken_command = "Pay ABC Suppliers twenty thousand rupees from my current account."
        
        # 1. Pipe instruction through the AI pipeline
        state = self.orchestrator.run_text_pipeline(spoken_command)
        
        # Assert validation detected insufficient balance
        self.assertFalse(state["validation_results"]["is_valid"])
        self.assertFalse(state["validation_results"]["sufficient_funds"])
        self.assertIn("Insufficient balance", state["validation_results"]["errors"][0])
        
        # 2. Try to save the draft
        draft_payload = {
            "debtor_account": state["debtor_account"]["account_number"] if state["debtor_account"] else None,
            "creditor_account": state["creditor_account"]["account_number"] if state["creditor_account"] else None,
            "amount": state["amount"],
            "currency": state["currency"],
            "payment_date": state["payment_date"],
            "category": state["category"],
            "notes": state["purpose"],
            "status": "Draft"
        }
        saved_draft = save_payment_draft(draft_payload)
        
        # 3. Attempt execution
        success, message = execute_payment(saved_draft["id"])
        
        # Assert transaction was blocked
        self.assertFalse(success)
        self.assertIn("insufficient balance", message.lower())
        
        # 4. Assert database balances remain untouched
        debtor_updated = get_account("11223344")
        creditor_updated = get_account("12345678")
        
        self.assertEqual(debtor_updated["balance"], 15000.0)
        self.assertEqual(creditor_updated["balance"], 0.0)

    def test_e2e_high_value_warning(self):
        """
        Test Case 8: Large Transaction Safety Warning E2E
        Scenario: Transaction exceeds safety threshold (> 100,000) but debtor has sufficient funds.
        Flow: Seed sufficient balance -> Pipeline -> Validator logs warning -> Execution works but flags warning.
        """
        # Set debtor balance to 500,000 INR to pass the balance checks
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE accounts SET balance = 500000.0 WHERE account_number = '11223344'")
        conn.commit()
        conn.close()

        # Request payment of 150,000 INR (exceeds 100,000 warning limit)
        spoken_command = "Pay ABC Suppliers one lakh fifty thousand rupees tomorrow from my current account."
        
        # 1. Pipe instruction through the AI pipeline
        state = self.orchestrator.run_text_pipeline(spoken_command)
        
        # Assert transaction is valid but triggers a high-value warning
        self.assertTrue(state["validation_results"]["is_valid"])
        self.assertEqual(state["amount"], 150000.0)
        self.assertEqual(len(state["validation_results"]["warnings"]), 1)
        self.assertIn("Large transaction amount", state["validation_results"]["warnings"][0])
        
        # 2. Save and execute the payment draft
        draft_payload = {
            "debtor_account": state["debtor_account"]["account_number"],
            "creditor_account": state["creditor_account"]["account_number"],
            "amount": state["amount"],
            "currency": state["currency"],
            "payment_date": state["payment_date"],
            "category": state["category"],
            "notes": state["purpose"],
            "status": "Draft"
        }
        saved_draft = save_payment_draft(draft_payload)
        success, message = execute_payment(saved_draft["id"])
        
        # Assert payment was allowed to complete since sufficient funds existed
        self.assertTrue(success)
        
        # 3. Assert correct deductions took place
        debtor_updated = get_account("11223344")
        self.assertEqual(debtor_updated["balance"], 350000.0) # 500k - 150k

    def test_e2e_missing_receiver(self):
        """
        Test Case 9: Incomplete Instruction Handling E2E
        Scenario: User speaks a payment command but forgets to specify the recipient.
        Flow: Input -> Pipeline -> Validation flags missing creditor -> Execution blocked.
        """
        spoken_command = "Pay five hundred rupees tomorrow from my savings account."
        
        # 1. Pipe instruction through the AI pipeline
        state = self.orchestrator.run_text_pipeline(spoken_command)
        
        # Assert validation fails on missing receiver
        self.assertFalse(state["validation_results"]["is_valid"])
        self.assertIn("Creditor (recipient) account was not identified", state["validation_results"]["errors"][0])
        self.assertIsNone(state["creditor_account"])
        
        # 2. Save draft
        draft_payload = {
            "debtor_account": state["debtor_account"]["account_number"] if state["debtor_account"] else None,
            "creditor_account": None,
            "amount": state["amount"],
            "currency": state["currency"],
            "payment_date": state["payment_date"],
            "category": state["category"],
            "notes": state["purpose"],
            "status": "Draft"
        }
        saved_draft = save_payment_draft(draft_payload)
        
        # 3. Try to execute the draft
        success, message = execute_payment(saved_draft["id"])
        
        # Assert transaction was rejected
        self.assertFalse(success)
        self.assertIn("incomplete or invalid", message.lower())


if __name__ == "__main__":
    unittest.main()
