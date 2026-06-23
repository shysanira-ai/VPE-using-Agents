"""
Audio Processor Module (ai/audio_processor.py)

PURPOSE:
Converts speech (audio files) into raw text transcripts. 
It supports multiple audio formats and provides a fallback mechanism 
if PyTorch/Whisper is not installed or fails due to system constraints (like missing ffmpeg).

MODEL SELECTION RATIONALE - WHY WHISPER?
1. OpenAI's Whisper is a state-of-the-art open-source sequence-to-sequence transformer model.
2. It has been trained on 680,000 hours of multilingual and multitask supervised data, making it 
   extremely robust to accents, background noise, and technical terms.
3. The 'tiny' model is lightweight (~70MB) and fast enough for CPU execution, satisfying our 
   average processing time limit (< 5 seconds).

FALLBACK SYSTEM - GOOGLE SPEECH API:
If PyTorch/Whisper is not available or if the OS lacks ffmpeg, the code falls back to the 
SpeechRecognition library (using Google's Web Speech API) which doesn't require binary dependencies.

INPUTS:
- audio_file_path (str): The absolute path to the audio file (.wav, .mp3, etc.)

OUTPUTS:
- transcript (str): The transcribed text from the audio, or an empty string with an error.

FLOW:
1. Receives path to WAV/MP3 file.
2. Tries to load Whisper model (using 'tiny' to optimize memory and CPU speed).
3. Transcribes audio and returns the text.
4. On failure or import error, routes processing to standard SpeechRecognition fallback.
"""

import os
import sys

# Flag to check if whisper is loaded successfully
HAS_WHISPER = False
whisper_model = None

try:
    import whisper
    import warnings
    # Suppress UserWarnings from Whisper/Torch regarding CPU/FP16 execution
    warnings.filterwarnings("ignore", category=UserWarning)
    HAS_WHISPER = True
except ImportError:
    print("[WARN] Whisper library not installed. Falling back to SpeechRecognition Google API.")

def get_whisper_model():
    """
    Lazy-loads the Whisper model to speed up server start time.
    Uses 'tiny' model for fast CPU inference.
    """
    global whisper_model
    if HAS_WHISPER and whisper_model is None:
        try:
            print("Loading Whisper 'tiny' model (will download on first run)...")
            whisper_model = whisper.load_model("tiny")
            print("Whisper model loaded successfully.")
        except Exception as e:
            print(f"[ERROR] Failed to load Whisper model: {e}. Fallback will be used.")
            return None
    return whisper_model

def transcribe_with_whisper(audio_path):
    """
    Transcribes audio using Whisper tiny model.
    """
    model = get_whisper_model()
    if model is None:
        raise Exception("Whisper model not initialized.")
        
    result = model.transcribe(audio_path, fp16=False) # fp16=False avoids CPU warning
    return result.get("text", "").strip()

def transcribe_with_fallback(audio_path):
    """
    Fallback transcription using the SpeechRecognition library and Google Speech API.
    Does not require ffmpeg or GPU/PyTorch.
    """
    try:
        import speech_recognition as sr
        
        recognizer = sr.Recognizer()
        
        # Open the audio file
        with sr.AudioFile(audio_path) as source:
            # Record the audio content
            audio_data = recognizer.record(source)
            
        print("Recognizing speech using Google Speech API fallback...")
        text = recognizer.recognize_google(audio_data)
        return text.strip()
        
    except ImportError:
        return "[Error] Neither Whisper nor SpeechRecognition libraries are fully configured. Install dependencies."
    except Exception as e:
        return f"[Error during transcription fallback]: {str(e)}"

def transcribe_audio(audio_file_path):
    """
    Main transcription entry point. Automatically routes between Whisper and Fallback.
    
    INPUT: audio_file_path (str)
    OUTPUT: transcribed text (str)
    """
    if not os.path.exists(audio_file_path):
        return f"[Error] Audio file not found at: {audio_file_path}"
        
    # Step 1: Try Whisper if available
    if HAS_WHISPER:
        try:
            print(f"Transcribing '{audio_file_path}' using Whisper tiny...")
            transcript = transcribe_with_whisper(audio_file_path)
            if transcript:
                return transcript
        except Exception as e:
            print(f"[WARN] Whisper failed ({e}). Attempting SpeechRecognition fallback...")
            
    # Step 2: Fallback to Google Speech API
    return transcribe_with_fallback(audio_file_path)
