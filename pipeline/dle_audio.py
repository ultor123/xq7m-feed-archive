#!/usr/bin/python3
"""
DLE Daily Audio Generator
Converts today's DLE advice text into an MP3 using Kokoro TTS (local, free).
Saves to iCloud Drive and optionally sends via Telegram.
"""

import kokoro
import soundfile as sf
import subprocess
import os
import sys
from datetime import date

# --- CONFIG ---
ICLOUD_DIR = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/DLE Audio")
_DLE_HOME = os.environ.get("DLE_HOME")
LOCAL_BACKUP = os.path.join(_DLE_HOME, "audio") if _DLE_HOME else os.path.expanduser("~/dle/feed-archive/audio")
VOICE = "af_heart"  # Kokoro voice: af_heart is warm, clear, female
SPEED = 1.0

# Telegram config (fill these in after setting up bot)
TELEGRAM_BOT_TOKEN = ""  # Get from @BotFather
TELEGRAM_CHAT_ID = ""    # Your personal chat ID


def generate_audio(text, output_path):
    """Generate audio from text using Kokoro TTS."""
    pipeline = kokoro.KPipeline(lang_code="a")  # 'a' = American English

    # Generate audio segments
    audio_segments = []
    for result in pipeline(text, voice=VOICE, speed=SPEED):
        audio_segments.append(result.audio)

    # Concatenate all segments
    import numpy as np
    full_audio = np.concatenate(audio_segments)

    # Save as WAV first, then convert to MP3
    wav_path = output_path.replace(".mp3", ".wav")
    sf.write(wav_path, full_audio, 24000)

    # Convert to MP3 using ffmpeg if available, otherwise keep WAV
    try:
        subprocess.run(
            ["ffmpeg", "-i", wav_path, "-b:a", "128k", "-y", output_path],
            capture_output=True, check=True
        )
        os.remove(wav_path)
        print(f"Saved MP3: {output_path}")
    except (FileNotFoundError, subprocess.CalledProcessError):
        # No ffmpeg, just rename WAV
        os.rename(wav_path, output_path.replace(".mp3", ".wav"))
        print(f"Saved WAV (install ffmpeg for MP3): {output_path.replace('.mp3', '.wav')}")


def send_telegram(audio_path):
    """Send audio file via Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured, skipping.")
        return

    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendAudio"
    with open(audio_path, "rb") as f:
        resp = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "title": f"DLE - {date.today().isoformat()}",
            "performer": "The Kiln Daily"
        }, files={"audio": f})

    if resp.status_code == 200:
        print("Sent to Telegram!")
    else:
        print(f"Telegram error: {resp.text}")


def main():
    today = os.environ.get("DLE_DATE") or date.today().isoformat()  # DLE_DATE allows backfilling past dates
    filename = f"DLE-{today}.mp3"

    # Read text from stdin or argument
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    if not text.strip():
        print("No text provided. Pass a file path as argument or pipe text via stdin.")
        sys.exit(1)

    # Ensure output dirs exist
    os.makedirs(LOCAL_BACKUP, exist_ok=True)

    # Generate audio — write to unprotected location first (load-bearing for GitHub publish)
    local_path = os.path.join(LOCAL_BACKUP, filename)
    print(f"Generating audio for {today}...")
    generate_audio(text, local_path)

    # Best-effort copy to iCloud (may fail under launchd TCC, that's OK — podcast still publishes)
    try:
        os.makedirs(ICLOUD_DIR, exist_ok=True)
        icloud_path = os.path.join(ICLOUD_DIR, filename)
        subprocess.run(["cp", local_path, icloud_path], check=False)
        print(f"Also copied to iCloud: {icloud_path}")
    except Exception as e:
        print(f"iCloud copy failed (non-fatal): {e}")

    # Send via Telegram (best-effort)
    try:
        send_telegram(local_path)
    except Exception as e:
        print(f"Telegram failed (non-fatal): {e}")

    print("Done!")


if __name__ == "__main__":
    main()
