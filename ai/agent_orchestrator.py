"""
Agent Orchestration Module (ai/agent_orchestrator.py)

PURPOSE:
Coordinates the multi-agent system that processes voice payments using the official LangGraph framework.
It defines the typed Graph State, specialized agent node functions, and constructs a compiled 
StateGraph workflow that is executed statefully and locally.

MODEL SELECTION RATIONALE:
1. **LangGraph StateGraph**: Leverages standard industry multi-agent design patterns.
   It compiles nodes (individual agent logic) and edges (transitions) into a stateful graph application.
2. **Offline Local Processing**: The workflow operates entirely locally on CPU (via spaCy, ChromaDB, 
   difflib, and Whisper) without requiring external LLM API credentials, satisfying the free tools requirement.

AGENT ROLES:
1. **Transcription Agent**: Converts raw audio data to string text.
2. **Extraction Agent (NER)**: Uses NLP to pull basic entities (amount, names, dates).
3. **Account Search Agent (RAG)**: Resolves raw text names to structured database rows via ChromaDB.
4. **Classification Agent**: Computes country-currency category and text-based purpose.
5. **Validation Agent**: Inspects values, runs business checks (e.g. balance check), and flags warnings.
"""

from typing import TypedDict, List, Optional, Dict, Any
from langgraph.graph import StateGraph, END

from ai.audio_processor import transcribe_audio
from ai.entity_extractor import extract_entities
from ai.vector_search import search_account
from ai.classifier import classify_payment_type, classify_payment_purpose
from database.db_manager import get_all_accounts


class AgentState(TypedDict):
    """
    State definition for the LangGraph agent execution pipeline.
    """
    audio_path: Optional[str]
    raw_text: str
    extracted_entities: Dict[str, Any]
    debtor_account: Optional[Dict[str, Any]]
    creditor_account: Optional[Dict[str, Any]]
    amount: Optional[float]
    currency: str
    payment_date: str
    category: str
    purpose: str
    validation_results: Dict[str, Any]
    execution_logs: List[str]


class VoicePaymentAgentOrchestrator:
    """
    Orchestrates the voice-payment LangGraph state machine pipeline.
    """
    
    def __init__(self):
        # Fetch standard accounts to determine default sender
        self.accounts = get_all_accounts()
        # Default debtor is San Shy's Current Account if none specified
        self.default_debtor_number = "11223344"
        for acc in self.accounts:
            if "current" in acc["account_holder"].lower():
                self.default_debtor_number = acc["account_number"]
                break
                
        # Build and compile the official LangGraph state workflow
        self.graph = self._build_workflow()

    def _build_workflow(self) -> StateGraph:
        """
        Creates and compiles the StateGraph workflow nodes and transitions.
        """
        workflow = StateGraph(AgentState)
        
        # 1. Register graph node functions
        workflow.add_node("transcription", self._transcription_node)
        workflow.add_node("ner", self._ner_node)
        workflow.add_node("rag_search", self._rag_search_node)
        workflow.add_node("classification", self._classification_node)
        workflow.add_node("validation", self._validation_node)
        
        # 2. Configure Entry Point and Path Routing
        workflow.set_entry_point("transcription")
        
        # Conditional transition from transcription
        # If transcription fails (empty/error), exit immediately; otherwise continue to NER extraction
        workflow.add_conditional_edges(
            "transcription",
            self._should_continue,
            {
                "continue": "ner",
                "end": END
            }
        )
        
        # Remaining sequential agent transitions
        workflow.add_edge("ner", "rag_search")
        workflow.add_edge("rag_search", "classification")
        workflow.add_edge("classification", "validation")
        workflow.add_edge("validation", END)
        
        return workflow.compile()

    # ==========================================
    # CONDITIONAL ROUTING FUNCTION
    # ==========================================

    def _should_continue(self, state: AgentState) -> str:
        """
        Determines if the pipeline should proceed or abort based on the transcript result.
        """
        text = state.get("raw_text", "")
        if not text or text.startswith("[Error]"):
            return "end"
        return "continue"

    # ==========================================
    # STATEGRAPH NODE FUNCTIONS
    # ==========================================

    def _transcription_node(self, state: AgentState) -> Dict[str, Any]:
        """
        TRANSCRIPTION NODE
        Converts the input audio file into natural language text.
        """
        logs = list(state.get("execution_logs", []))
        logs.append("Transcription Agent: Transcribing audio file...")
        
        audio_path = state.get("audio_path")
        if not audio_path:
            # Skip transcription node if running a raw text pipeline directly
            return {"execution_logs": logs}
            
        try:
            text = transcribe_audio(audio_path)
            logs.append(f"Transcription Agent Success. Text: '{text}'")
            
            # Catch errors returned by speech transcript fallback
            if not text or text.startswith("[Error]"):
                val = {
                    "is_valid": False,
                    "errors": ["Transcription failed."],
                    "warnings": [],
                    "balance_checked": False,
                    "sufficient_funds": True
                }
                return {
                    "raw_text": text or "[Error] Empty transcript",
                    "validation_results": val,
                    "execution_logs": logs + ["Transcription Agent Failed: Aborting pipeline."]
                }
                
            return {
                "raw_text": text,
                "execution_logs": logs
            }
        except Exception as e:
            val = {
                "is_valid": False,
                "errors": [f"Transcription failed: {str(e)}"],
                "warnings": [],
                "balance_checked": False,
                "sufficient_funds": True
            }
            logs.append(f"Transcription Agent Failed: {str(e)}")
            return {
                "raw_text": f"[Error] {str(e)}",
                "validation_results": val,
                "execution_logs": logs
            }

    def _ner_node(self, state: AgentState) -> Dict[str, Any]:
        """
        EXTRACTION NODE (NER)
        Extracts structured entities from the natural language text.
        """
        text = state.get("raw_text", "")
        logs = list(state.get("execution_logs", []))
        logs.append("NER Agent: Parsing natural language text...")
        
        extracted = extract_entities(text)

        #print("raw text...", text)
        #print("extracted text...", extracted)

        logs.append(
            f"NER Agent Success. Extracted values: Amount={extracted.get('amount')}, "
            f"Currency={extracted.get('currency', 'INR')}, Date={extracted.get('payment_date')}"
        )
        
        return {
            "extracted_entities": extracted,
            "creditor": extracted.get("creditor"),
            "amount": extracted.get("amount"),
            "currency": extracted.get("currency", "INR"),
            "payment_date": extracted.get("payment_date", ""),
            "execution_logs": logs
        }

    def _rag_search_node(self, state: AgentState) -> Dict[str, Any]:
        """
        RAG SEARCH NODE
        Resolves query names to exact database accounts using ChromaDB/Fuzzy fallback.
        """
        logs = list(state.get("execution_logs", []))
        logs.append("RAG Search Agent: Querying ChromaDB vector database for account names...")
        
        extracted = state.get("extracted_entities", {})
        debtor_query = extracted.get("debtor")
        creditor_query = extracted.get("creditor")
        
        #print("creditor_query...", creditor_query)

        debtor_account = None
        creditor_account = None
        
        # 1. Debtor (Sender) Resolution
        if debtor_query:
            debtor_acc = search_account(debtor_query)
            if debtor_acc:
                debtor_account = debtor_acc
                logs.append(f"RAG Agent: Resolved Debtor query '{debtor_query}' to '{debtor_acc['account_holder']}' ({debtor_acc['account_number']})")
            else:
                logs.append(f"RAG Agent: Debtor query '{debtor_query}' yielded no matches. Defaulting.")
        
        # Default debtor fallback
        if not debtor_account:
            from database.db_manager import get_account
            default_acc = get_account(self.default_debtor_number)
            debtor_account = default_acc
            logs.append(f"RAG Agent: Debtor set to default account: '{default_acc['account_holder']}'")
            
        # 2. Creditor (Receiver) Resolution
        if creditor_query:
            creditor_acc = search_account(creditor_query)
            if creditor_acc:
                creditor_account = creditor_acc
                logs.append(f"RAG Agent: Resolved Creditor query '{creditor_query}' to '{creditor_acc['account_holder']}' ({creditor_acc['account_number']})")
            else:
                logs.append(f"RAG Agent: Creditor query '{creditor_query}' yielded no matches.")
        else:
            logs.append("RAG Agent: No creditor name detected in voice command.")
            
        return {
            "debtor_account": debtor_account,
            "creditor_account": creditor_account,
            "execution_logs": logs
        }

    def _classification_node(self, state: AgentState) -> Dict[str, Any]:
        """
        CLASSIFICATION NODE
        Determines FX payment regulatory type and business reason classifications.
        """
        logs = list(state.get("execution_logs", []))
        logs.append("Classification Agent: Analyzing payment category and purpose...")
        
        debtor = state.get("debtor_account")
        creditor = state.get("creditor_account")
        currency = state.get("currency", "INR")
        text = state.get("raw_text", "")
        
        # Calculate domestic/intl FX status
        category = classify_payment_type(debtor, creditor, currency)
        
        # Extract business category tag
        purpose = classify_payment_purpose(text)
        
        logs.append(f"Classification Agent Success. Type='{category}', Purpose='{purpose}'")
        
        return {
            "category": category,
            "purpose": purpose,
            "execution_logs": logs
        }

    def _validation_node(self, state: AgentState) -> Dict[str, Any]:
        """
        VALIDATION NODE
        Performs integrity tests, amount verification, and checks balances.
        """
        logs = list(state.get("execution_logs", []))
        logs.append("Validation Agent: Performing payment integrity checks...")
        
        # Clone or initialize a fresh validation dict
        val = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "balance_checked": False,
            "sufficient_funds": True
        }
        
        amount = state.get("amount")
        debtor = state.get("debtor_account")
        creditor = state.get("creditor_account")
        currency = state.get("currency", "INR")
        
        # 1. Complete amount validation
        if amount is None or amount <= 0:
            val["is_valid"] = False
            val["errors"].append("Transaction amount is missing or invalid.")
            logs.append("Validation Agent Error: Invalid transaction amount.")
            
        # 2. Account checks
        if not debtor:
            val["is_valid"] = False
            val["errors"].append("Debtor (sender) account details are missing.")
            logs.append("Validation Agent Error: Missing sender account.")
            
        if not creditor:
            val["is_valid"] = False
            val["errors"].append("Creditor (recipient) account was not identified in command.")
            logs.append("Validation Agent Error: Missing receiver account.")
            
        # 3. Solvency / Balance checks
        if debtor and amount and amount > 0:
            val["balance_checked"] = True
            debtor_balance = debtor.get("balance", 0.0)
            
            if debtor_balance < amount:
                val["sufficient_funds"] = False
                val["is_valid"] = False
                err_msg = f"Insufficient balance in account '{debtor['account_holder']}'. Available: {debtor_balance} {debtor['currency']}. Required: {amount} {currency}."
                val["errors"].append(err_msg)
                logs.append(f"Validation Agent Error: {err_msg}")
            else:
                val["sufficient_funds"] = True
                logs.append(f"Validation Agent Success: Debtor has sufficient balance ({debtor_balance} >= {amount}).")
                
        # 4. Threshold safety limits
        if amount and amount > 100000:
            val["warnings"].append("Large transaction amount. Requires additional manager confirmation.")
            logs.append("Validation Agent Warning: High-value transaction flagged.")
            
        logs.append("Pipeline execution completed successfully.")
        
        return {
            "validation_results": val,
            "execution_logs": logs
        }

    # ==========================================
    # PUBLIC ENTRY ENDPOINTS
    # ==========================================

    def run_audio_pipeline(self, audio_path: str) -> Dict[str, Any]:
        """
        Executes the compiled LangGraph workflow starting with an audio file path.
        """
        initial_state = {
            "audio_path": audio_path,
            "raw_text": "",
            "extracted_entities": {},
            "debtor_account": None,
            "creditor_account": None,
            "amount": None,
            "currency": "INR",
            "payment_date": "",
            "category": "",
            "purpose": "",
            "validation_results": {
                "is_valid": True,
                "errors": [],
                "warnings": [],
                "balance_checked": False,
                "sufficient_funds": True
            },
            "execution_logs": ["Pipeline started with audio input."]
        }
        
        # Invoke LangGraph
        return self.graph.invoke(initial_state)

    def run_text_pipeline(self, raw_text: str) -> Dict[str, Any]:
        """
        Executes the compiled LangGraph workflow starting with raw text commands.
        Bypasses the actual audio transcription node automatically inside the nodes.
        """
        initial_state = {
            "audio_path": None,
            "raw_text": raw_text,
            "extracted_entities": {},
            "debtor_account": None,
            "creditor_account": None,
            "amount": None,
            "currency": "INR",
            "payment_date": "",
            "category": "",
            "purpose": "",
            "validation_results": {
                "is_valid": True,
                "errors": [],
                "warnings": [],
                "balance_checked": False,
                "sufficient_funds": True
            },
            "execution_logs": ["Pipeline started with raw text input."]
        }
        
        # Invoke LangGraph
        return self.graph.invoke(initial_state)
