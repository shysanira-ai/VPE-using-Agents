"""
Backend FastAPI Application (backend/app.py)

PURPOSE:
Serves as the central API gateway and static web host for the Voice-Based Payment system.
Exposes endpoints for audio file uploads, voice transcription + entity processing, 
relational SQLite account queries, and payment draft management.

FLOW:
1. Initialize FastAPI app.
2. Setup CORS origins and mount the frontend folder as static files to serve the UI.
3. `/api/transcribe` (POST): Saves uploaded WAV file, runs the AI Orchestrator audio pipeline, 
   and returns the parsed structured results.
4. `/api/process-text` (POST): Processes a raw text command, runs the AI Orchestrator, and returns fields.
5. `/api/accounts` (GET): Fetches account profiles (debtor, creditor lists) for UI selection.
6. `/api/drafts` (GET/POST): Queries and updates payment drafts in the relational database.
7. `/api/submit-payment` (POST): Completes the transaction by deducting from debtor's balance.

INPUTS & OUTPUTS:
- Inputs: Form uploads (audio files), raw texts, payment JSON configurations.
- Outputs: Transaction status records, payment details, error logs, and validation messages.
"""

import os
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

# Import local database and AI orchestration interfaces
from database.db_manager import (
    get_all_accounts,
    get_all_drafts,
    save_payment_draft,
    execute_payment,
    init_db
)
from ai.agent_orchestrator import VoicePaymentAgentOrchestrator
from ai.vector_search import sync_accounts_to_vector_db

app = FastAPI(title="Voice-Based Payment API", version="1.0.0")

# Setup CORS to allow local testing from multiple browser ports
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Establish temporary directory path for audio processing
TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio")
os.makedirs(TEMP_DIR, exist_ok=True)

# Initialize global agent orchestrator
orchestrator = VoicePaymentAgentOrchestrator()

# Pydantic schemas for request validation
class TextRequest(BaseModel):
    text: str

class DraftRequest(BaseModel):
    id: Optional[int] = None
    debtor_account: str
    creditor_account: str
    amount: float
    currency: str
    payment_date: str
    category: str
    notes: Optional[str] = ""
    status: Optional[str] = "Draft"

class PaymentSubmitRequest(BaseModel):
    draft_id: int

@app.on_event("startup")
def startup_event():
    """
    Ensures SQLite tables are created and indexed in ChromaDB on application startup.
    """
    init_db()
    sync_accounts_to_vector_db()
    print("Backend server initialized and databases synced.")

# ==========================================
# API ENDPOINTS
# ==========================================

@app.get("/api/accounts")
def api_get_accounts():
    """
    Retrieves all registered bank accounts.
    """
    try:
        return get_all_accounts()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")

@app.get("/api/drafts")
def api_get_drafts():
    """
    Retrieves the transaction history list of payment drafts.
    """
    try:
        return get_all_drafts()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")

@app.post("/api/drafts")
def api_save_draft(draft: DraftRequest):
    """
    Saves a transaction draft.
    """
    try:
        saved_record = save_payment_draft(draft.dict())
        # Sync ChromaDB with any potential account balance modifications (if any occur)
        sync_accounts_to_vector_db()
        return {"success": True, "draft": saved_record}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save payment draft: {str(e)}")

@app.post("/api/submit-payment")
def api_submit_payment(request: PaymentSubmitRequest):
    """
    Submits a finalized payment, validates credentials, and performs balance checks.
    """
    success, message = execute_payment(request.draft_id)
    if not success:
         raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message}

@app.post("/api/transcribe")
async def api_transcribe_audio(file: UploadFile = File(...)):
    """
    Accepts raw audio file uploads, saves them temporarily, 
    and pipes them through the multi-agent AI pipeline.
    """
    # 1. Verify file extension
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in [".wav", ".mp3", ".webm", ".ogg"]:
        raise HTTPException(status_code=400, detail="Unsupported audio format. Please upload WAV, MP3, or WebM.")

    # 2. Save file locally in temp folder
    temp_file_path = os.path.join(TEMP_DIR, f"upload_{file.filename}")
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # 3. Process file using Agent Orchestrator
        print(f"Piping audio file '{temp_file_path}' through AI Agent Orchestrator...")
        pipeline_state = orchestrator.run_audio_pipeline(temp_file_path)
        
        return pipeline_state
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audio processing failure: {str(e)}")
    finally:
        # 4. Clean up temporary audio file to save disk space
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass

@app.post("/api/process-text")
def api_process_text(request: TextRequest):
    """
    Accepts manual text adjustments and re-runs the AI Extraction pipeline.
    This enables users to correct transcription typos or perform test sentences.
    """
    try:
        print(f"Piping command text '{request.text}' through AI Agent Orchestrator...")
        pipeline_state = orchestrator.run_text_pipeline(request.text)
        return pipeline_state
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Text processing failure: {str(e)}")

# ==========================================
# STATIC FILES SERVING (UI)
# ==========================================
# Mount the frontend directory to serve HTML, CSS, JS assets.
# Note: Keep at the end to prevent catching API endpoints.
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    print(f"[WARN] Frontend directory not found at: {FRONTEND_DIR}. Server will run API-only mode.")
