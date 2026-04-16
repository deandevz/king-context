#!/usr/bin/env python3
"""
MiniMax Text-to-Speech (T2A) CLI Script
========================================

Converts text to speech using the MiniMax T2A HTTP API (v1/t2a_v2).
Outputs an MP3 file to the output/ directory.

Usage:
    python minimax_tts.py "Your text here"
    python minimax_tts.py                    # interactive mode (prompts for text)

Configuration:
    Copy .env.example to .env and set your MINIMAX_API_KEY.
    All other settings have sensible defaults.

API Reference:
    https://platform.minimax.io/docs/api-reference/speech-t2a-http
"""

import sys
import os
import argparse
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration — loads values from .env in the same directory as this script
# ---------------------------------------------------------------------------

# Resolve .env relative to this script's location (not the caller's cwd)
SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

# Required: MiniMax API key (Bearer token)
API_KEY = os.getenv("MINIMAX_API_KEY", "")

# MiniMax T2A HTTP endpoint
API_URL = "https://api.minimax.io/v1/t2a_v2"

# Model selection — speech-2.8-hd offers the best quality;
# speech-2.8-turbo is faster but slightly lower quality
MODEL = os.getenv("MINIMAX_MODEL", "speech-2.8-hd")

# Voice ID — "English_expressive_narrator" is the default English voice.
# Use the /v1/get_voice API to discover all available system + cloned voices.
VOICE_ID = os.getenv("MINIMAX_VOICE_ID", "English_expressive_narrator")

# Speech speed: 0.5 (slow) to 2.0 (fast), default 1.0
SPEED = float(os.getenv("MINIMAX_SPEED", "1.0"))

# Language boost helps the model recognize specific languages.
# Set to "auto" for automatic detection, a language name (e.g. "English"),
# or empty string to disable.
LANGUAGE_BOOST = os.getenv("MINIMAX_LANGUAGE_BOOST", "auto") or None

# Audio encoding settings
SAMPLE_RATE = int(os.getenv("MINIMAX_SAMPLE_RATE", "32000"))
BITRATE = int(os.getenv("MINIMAX_BITRATE", "128000"))

# Output directory for generated audio files
OUTPUT_DIR = SCRIPT_DIR / "output"


def validate_config() -> None:
    """Check that the required configuration is present before making API calls."""
    if not API_KEY or API_KEY == "your_api_key_here":
        print("Error: MINIMAX_API_KEY is not set.")
        print("Copy .env.example to .env and add your API key:")
        print(f"  cp {SCRIPT_DIR / '.env.example'} {SCRIPT_DIR / '.env'}")
        sys.exit(1)


def build_request_body(text: str) -> dict:
    """
    Build the JSON payload for the MiniMax T2A v2 endpoint.

    Parameters follow the official API reference:
    - model: speech synthesis model version
    - text: the text to convert (max 10,000 characters)
    - stream: false for a single complete response
    - voice_setting: voice ID, speed, volume, pitch
    - audio_setting: sample rate, bitrate, format, channels
    - output_format: "hex" returns hex-encoded audio in JSON response
    - language_boost: optional language detection hint
    """
    body = {
        # Model version — speech-2.8-hd is the latest high-definition model
        "model": MODEL,

        # The text to synthesize into speech
        "text": text,

        # Non-streaming mode: returns the complete audio in one response
        "stream": False,

        # Voice configuration
        "voice_setting": {
            "voice_id": VOICE_ID,   # Which voice to use
            "speed": SPEED,         # Playback speed multiplier
            "vol": 1,               # Volume (1 = normal)
            "pitch": 0,             # Pitch shift (0 = no change)
        },

        # Audio encoding configuration
        "audio_setting": {
            "sample_rate": SAMPLE_RATE,  # Hz — 32000 is recommended
            "bitrate": BITRATE,          # bps — 128000 for good quality
            "format": "mp3",             # Output format: mp3, wav, or flac
            "channel": 1,                # 1 = mono (sufficient for speech)
        },

        # Output format: "hex" embeds the audio as a hex string in the JSON response.
        # Alternative: "url" returns a temporary download URL (valid 24h).
        "output_format": "hex",
    }

    # Only include language_boost if configured (avoids sending null)
    if LANGUAGE_BOOST:
        body["language_boost"] = LANGUAGE_BOOST

    return body


def call_minimax_tts(text: str) -> bytes:
    """
    Send text to the MiniMax T2A API and return the raw MP3 audio bytes.

    The API returns a JSON response with:
    - data.audio: hex-encoded audio string
    - data.status: 2 means generation complete
    - base_resp.status_code: 0 means success
    - extra_info: metadata (duration, size, sample rate, etc.)

    Raises SystemExit on API errors for clear CLI feedback.
    """
    # Build the request payload
    payload = build_request_body(text)

    # Set authorization header with Bearer token
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    print(f"Sending request to MiniMax ({MODEL})...")

    try:
        # POST to the T2A v2 endpoint with a generous timeout
        # (large texts can take a while to synthesize)
        response = requests.post(
            API_URL,
            json=payload,
            headers=headers,
            timeout=120,
        )
    except requests.exceptions.RequestException as e:
        print(f"Error: Network request failed — {e}")
        sys.exit(1)

    # Parse the JSON response
    result = response.json()

    # Check the API-level status (base_resp.status_code == 0 means success)
    base_resp = result.get("base_resp", {})
    status_code = base_resp.get("status_code", -1)
    if status_code != 0:
        status_msg = base_resp.get("status_msg", "Unknown error")
        print(f"Error: API returned status {status_code} — {status_msg}")
        sys.exit(1)

    # Extract the audio data (hex-encoded string)
    data = result.get("data")
    if not data or not data.get("audio"):
        print("Error: API response missing audio data.")
        print(f"Full response: {result}")
        sys.exit(1)

    # Print useful metadata from extra_info
    extra = result.get("extra_info", {})
    duration_ms = extra.get("audio_length", 0)
    audio_size = extra.get("audio_size", 0)
    char_count = extra.get("usage_characters", 0)
    print(f"Audio generated: {duration_ms}ms duration, "
          f"{audio_size / 1024:.1f}KB, {char_count} characters billed")

    # Decode the hex string into raw audio bytes
    # The API returns audio as a hex-encoded string when output_format="hex"
    audio_hex = data["audio"]
    audio_bytes = bytes.fromhex(audio_hex)

    return audio_bytes


def save_audio(audio_bytes: bytes) -> Path:
    """
    Save raw audio bytes to an MP3 file in the output/ directory.

    Filename is based on the current timestamp for easy identification:
        output/tts_20260416_143052.mp3
    """
    # Ensure the output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate a timestamped filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"tts_{timestamp}.mp3"

    # Write the raw MP3 bytes to disk
    output_path.write_bytes(audio_bytes)

    return output_path


def parse_args() -> argparse.Namespace:
    """
    Parse CLI arguments.

    Supports two modes:
    1. Positional argument:  python minimax_tts.py "Hello world"
    2. Interactive mode:     python minimax_tts.py  (prompts for text)
    """
    parser = argparse.ArgumentParser(
        description="Convert text to speech using MiniMax T2A API",
        epilog="Example: python minimax_tts.py \"Hello, this is a test.\"",
    )
    parser.add_argument(
        "text",
        nargs="?",       # Optional — if missing, we'll prompt interactively
        default=None,
        help="Text to convert to speech (max 10,000 characters)",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point — validates config, gets text, calls API, saves audio."""

    # Step 1: Validate that the API key is configured
    validate_config()

    # Step 2: Get the text to synthesize (from CLI arg or interactive prompt)
    args = parse_args()
    text = args.text

    if not text:
        # Interactive mode — prompt the user for text input
        print("Enter the text to convert to speech (press Enter when done):")
        text = input("> ").strip()

    if not text:
        print("Error: No text provided.")
        sys.exit(1)

    # Warn if text exceeds the API limit
    if len(text) > 10_000:
        print(f"Warning: Text is {len(text)} characters (max 10,000). It will be truncated by the API.")

    # Step 3: Call the MiniMax T2A API
    audio_bytes = call_minimax_tts(text)

    # Step 4: Save the MP3 file
    output_path = save_audio(audio_bytes)
    print(f"Audio saved to: {output_path}")


if __name__ == "__main__":
    main()
