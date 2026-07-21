#!/usr/bin/python3
"""
Auto-generate today's DLE text using the Claude API.
Pulls from context library, avoids dates already in DLE Advice.md.
Writes the result to a temp file for the audio pipeline to consume.
"""

import os
import re
import sys
import json
from datetime import date
from pathlib import Path

# Generation runs through the Claude Code CLI on Ultan's subscription (not the
# paid Anthropic API). We deliberately strip ANTHROPIC_API_KEY from the CLI's
# environment so it authenticates via the subscription OAuth login instead of a
# (possibly depleted) API key that may be exported in the shell.
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")
if not os.path.exists(CLAUDE_BIN):
    CLAUDE_BIN = "claude"  # fall back to PATH lookup
MODEL = "claude-sonnet-4-6"

# Paths — DLE_HOME lets the same code run locally (~/dle) and in CI ($GITHUB_WORKSPACE)
DLE_HOME = os.environ.get("DLE_HOME", os.path.expanduser("~/dle"))
DLE_FILE = os.path.join(DLE_HOME, "data/DLE_Advice.md")
CONTEXT_DIR = os.path.join(DLE_HOME, "data/context")
OUTPUT_TEXT = os.environ.get("DLE_OUT_TEXT", "/tmp/dle_today_text.md")
OUTPUT_AUDIO_SCRIPT = os.environ.get("DLE_OUT_AUDIO", "/tmp/dle_today_audio.txt")

today = os.environ.get("DLE_DATE") or date.today().isoformat()  # DLE_DATE allows backfilling past dates


def read_dle_history():
    if not os.path.exists(DLE_FILE):
        return "", []
    with open(DLE_FILE) as f:
        content = f.read()
    dates_used = re.findall(r'^## (\d{4}-\d{2}-\d{2})', content, flags=re.MULTILINE)
    # Get last 2000 chars for recent context
    tail = content[-5000:]
    return tail, dates_used


def read_context_files():
    """Read all distilled context files (soundbites + books)."""
    files = []
    for f in sorted(Path(CONTEXT_DIR).glob("*.md")):
        files.append((f.name, f.read_text()))
    return files


def build_prompt():
    import random
    recent_dle, dates_used = read_dle_history()
    context_files = read_context_files()

    # Rotate context daily — send 5 files per day (1 soundbites + 4 random "deep" sources)
    # Deep sources = books, podcast transcripts (senra), thinker corpora (naval, etc.)
    # This keeps the prompt manageable and the daily output fresher.
    soundbite_files = [f for f in context_files if "soundbites" in f[0] or "frameworks" in f[0]]
    deep_files = [
        f for f in context_files
        if f[0].startswith("book_")
        or f[0].startswith("podcast_")   # distilled podcast episodes (e.g. Hormozi on DOAC)
        or "senra" in f[0]
        or f[0].startswith("naval")
    ]

    # Seed by date so the same day always picks the same files (reproducible)
    rng = random.Random(today)
    picked_deep = rng.sample(deep_files, min(4, len(deep_files)))
    picked_soundbite = rng.choice(soundbite_files) if soundbite_files else None

    selected = ([picked_soundbite] if picked_soundbite else []) + picked_deep
    context_bundle = "\n\n".join(
        f"=== {name} ===\n{text[:6000]}"  # cap each file
        for name, text in selected
    )

    avoid_list = ", ".join(dates_used[-25:])  # last 25 entries

    return f"""You are writing Ultan's Daily Learning and Enrichment (DLE) entry for {today}.

Ultan is a 27-year-old Irish entrepreneur in Portugal, MIT grad, building The Kiln (GTM infrastructure agency, $20k/mo, targeting 100k MRR). He uses the DLE for podcast appearances, client pitches, and daily intellectual sharpening.

OUTPUT FORMAT — produce TWO sections separated by `===AUDIO===`:

**Section 1 (Markdown for the DLE file):** Use this exact structure:

## {today}

### 1. The Funny One
> "quote"
Brief deployment context.

### 2. Business Insight
**A — [source]:** Short punchy insight, Kiln-specific application.
**B — [source]:** Same.

### 3. Deep Line
> "quote" — Attribution
1-2 sentence reframe.

### 4. Thought Principle: [name]
2-3 sentences explaining it + Kiln application.

### 5. New Words & Terms
**Word1** — definition + usage example.
**Word2** — same.
**Word3** — same.

### 6. Stoic Closer
> "quote" — Attribution
One sentence.

### 7. Daily Math: [concept]
Concept + business example + insight + today's exercise. Math should progress through this curriculum: Expected Value, Bayes' Theorem, Law of Large Numbers, Standard Deviation, Normal Distribution, Confidence Intervals, Regression to the Mean, Pareto Distribution, Conditional Probability, Monte Carlo, Markov Chains, Kelly Criterion. Check the recent DLE entries below to see what's been covered — do the NEXT topic in the sequence.

**Section 2 (Plain text for audio):** Same content but written for text-to-speech. Use "number one" instead of "1.", spell out symbols, avoid markdown. Start with "Your daily learning and enrichment for [date in spoken form]." End with "That's your daily learning and enrichment. Go make it count."

RULES:
- NEVER repeat a quote, word, or concept that's appeared in recent DLE entries (see below).
- Pull material from the context library (soundbites + 11 distilled books + DLE Advice history).
- Sharp, Irish wit. Self-deprecating but confident. Avoid LinkedIn-ese.
- Specific, concrete, quotable. No vague platitudes.

DATES ALREADY USED (avoid repeating their material): {avoid_list}

RECENT DLE ENTRIES (the last few days — don't repeat anything here):
{recent_dle}

CONTEXT LIBRARY (rotating subset — 5 files chosen by today's date):
{context_bundle[:35000]}

Now write today's DLE entry. Output the markdown section, then `===AUDIO===` on its own line, then the audio script."""


def call_claude(prompt):
    """Generate via the Claude Code CLI in headless print mode (subscription auth).

    Tools and MCP servers are disabled so the run is a pure text completion that
    can't hang on an interactive MCP auth prompt at 6am.
    """
    import subprocess
    import time

    # Strip the API key so the CLI uses the subscription login, not paid credits.
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)

    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--model", MODEL,
        "--disallowedTools", "*",
        "--strict-mcp-config",
        "--output-format", "text",
    ]

    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, env=env,
                timeout=1800, cwd=DLE_HOME,
            )
        except subprocess.TimeoutExpired:
            if attempt == max_attempts:
                raise
            wait = min(60, 5 * (2 ** (attempt - 1)))
            print(f"CLI timed out, retry {attempt}/{max_attempts} in {wait}s...", file=sys.stderr)
            time.sleep(wait)
            continue

        out = proc.stdout.strip()
        if proc.returncode == 0 and out:
            return out

        err = (proc.stderr.strip() or out or "no output")[:500]
        if attempt == max_attempts:
            raise RuntimeError(f"claude CLI failed (exit {proc.returncode}): {err}")
        wait = min(60, 5 * (2 ** (attempt - 1)))
        print(f"CLI error (exit {proc.returncode}): {err} — retry {attempt}/{max_attempts} in {wait}s...", file=sys.stderr)
        time.sleep(wait)


def main():
    print(f"Generating DLE for {today}...")
    prompt = build_prompt()
    result = call_claude(prompt)

    # Split into markdown and audio
    if "===AUDIO===" in result:
        md_part, audio_part = result.split("===AUDIO===", 1)
    else:
        md_part = result
        audio_part = re.sub(r'[*#>`\[\]]', '', result)

    md_part = md_part.strip()
    audio_part = audio_part.strip()

    with open(OUTPUT_TEXT, "w") as f:
        f.write(md_part)
    with open(OUTPUT_AUDIO_SCRIPT, "w") as f:
        f.write(audio_part)

    print(f"Markdown saved: {OUTPUT_TEXT} ({len(md_part)} chars)")
    print(f"Audio script saved: {OUTPUT_AUDIO_SCRIPT} ({len(audio_part)} chars)")


if __name__ == "__main__":
    main()
