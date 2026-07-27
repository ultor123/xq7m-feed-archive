#!/usr/bin/python3
"""
Auto-generate today's DLE (Daily Learning & Enrichment) episode text.

Segment-pool model: the library is pre-shredded into per-segment pools under
data/segments/. Each episode pulls ONE unused item from each pool (three from
vocabulary), records what was used so nothing repeats until a pool is exhausted,
then hands those specific items to Claude to write the episode around them.
Generation runs through the Claude Code CLI on Ultan's subscription.
"""

import os
import re
import sys
import json
import random
import hashlib
from datetime import date
from pathlib import Path

# --- Claude CLI (subscription auth; API key stripped in call_claude) ---
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")
if not os.path.exists(CLAUDE_BIN):
    CLAUDE_BIN = "claude"
MODEL = "claude-sonnet-4-6"

# --- Paths (DLE_HOME = ~/dle locally, $GITHUB_WORKSPACE in CI) ---
DLE_HOME = os.environ.get("DLE_HOME", os.path.expanduser("~/dle"))
DLE_FILE = os.path.join(DLE_HOME, "data/DLE_Advice.md")
SEG_DIR = os.path.join(DLE_HOME, "data/segments")
USED_FILE = os.path.join(SEG_DIR, "_used.json")
OUTPUT_TEXT = os.environ.get("DLE_OUT_TEXT", "/tmp/dle_today_text.md")
OUTPUT_AUDIO_SCRIPT = os.environ.get("DLE_OUT_AUDIO", "/tmp/dle_today_audio.txt")

today = os.environ.get("DLE_DATE") or date.today().isoformat()

# Episode segments: (pool slug, episode section label, how many items to pull)
SEGMENTS = [
    ("humor",      "The Funny One",      1),
    ("business",   "Business Insight",   1),
    ("philosophy", "Deep Line",          1),
    ("frameworks", "Thought Principle",  1),
    ("vocabulary", "New Words & Terms",  3),
    ("stoic",      "Stoic Closer",       1),
    ("contrarian", "Contrarian Take",    1),
    ("analogies",  "Analogy",            1),
    ("stories",    "Story",              1),
    ("rules",      "Rule of Thumb",      1),
    ("advertising","Ad Craft",           1),
]


def _hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def load_pool(slug):
    path = os.path.join(SEG_DIR, f"seg_{slug}.md")
    items = []
    if not os.path.exists(path):
        return items
    for ln in open(path):
        ln = ln.rstrip("\n")
        if ln.startswith("- "):
            text = ln[2:].strip()
            if text:
                items.append((_hash(text), text))
    return items


def load_used():
    if os.path.exists(USED_FILE):
        try:
            return json.load(open(USED_FILE))
        except Exception:
            return {}
    return {}


def save_used(used):
    os.makedirs(SEG_DIR, exist_ok=True)
    json.dump(used, open(USED_FILE, "w"), indent=0)


def pick_items():
    """Return {slug: [(hash, text), ...]} choosing unused items per pool.
    Reproducible per date; recycles a pool once every item has been used."""
    used = load_used()
    picks = {}
    for slug, _label, n in SEGMENTS:
        pool = load_pool(slug)
        if not pool:
            picks[slug] = []
            continue
        used_set = set(used.get(slug, []))
        available = [it for it in pool if it[0] not in used_set]
        if len(available) < n:  # exhausted -> recycle this pool
            used_set = set()
            available = pool
        rng = random.Random(f"{today}-{slug}")
        chosen = rng.sample(available, min(n, len(available)))
        picks[slug] = chosen
    return picks


def mark_used(picks):
    used = load_used()
    for slug, chosen in picks.items():
        cur = set(used.get(slug, []))
        pool_size = len(load_pool(slug))
        for h, _t in chosen:
            cur.add(h)
        if len(cur) >= pool_size:  # fully cycled -> reset
            cur = set(h for h, _ in chosen)
        used[slug] = sorted(cur)
    save_used(used)


def read_dle_history():
    if not os.path.exists(DLE_FILE):
        return "", []
    content = open(DLE_FILE).read()
    dates_used = re.findall(r'^## (\d{4}-\d{2}-\d{2})', content, flags=re.MULTILINE)
    return content[-4000:], dates_used


def build_prompt():
    recent_dle, _dates = read_dle_history()
    picks = pick_items()

    # Assemble the selected source items, one block per segment.
    blocks = []
    for slug, label, _n in SEGMENTS:
        chosen = picks.get(slug, [])
        if not chosen:
            continue
        lines = "\n".join(f"  - {t}" for _h, t in chosen)
        blocks.append(f"### {label} (from the '{slug}' pool)\n{lines}")
    material = "\n\n".join(blocks)

    prompt = f"""You are writing Ultan's Daily Learning and Enrichment (DLE) episode for {today}.

Ultan is a 27-year-old Irish entrepreneur in Portugal, MIT grad, building The Kiln (GTM infrastructure agency, $20k/mo, targeting 100k MRR). He uses the DLE for podcast appearances, client pitches, and daily intellectual sharpening.

I have pre-selected the raw source material for each section below. Your job is to WRITE UP each section around its selected item(s) — expand it, sharpen it, and add a concrete Kiln/GTM application or a deployment note. Keep source attributions where they exist. Do NOT swap in different quotes; use the ones provided. Sharp, Irish wit; self-deprecating but confident; specific and quotable; no LinkedIn-ese; no vague platitudes.

DELIVERY STYLE (write in this voice — modeled on Shaan Puri, layered on the Irish wit):
- Drag big/abstract/impressive things down into plain, tactile, everyday language.
- Explain via vivid everyday analogies (movies, sports, video games, groceries, childhood) — state the mapping plainly.
- Think in systems: name the reusable move, not just the story.
- Self-deprecate straight, no wink; puncture pretense. Make high stakes sound casual — the gap between stakes and register is the punch.
- Short punchy sentences; concrete numbers and names over abstraction. Occasionally build a vivid metaphor then flatten it with a mundane aside.

SELECTED MATERIAL:
{material}

OUTPUT FORMAT — produce TWO sections separated by a line containing only `===AUDIO===`.

**Section 1 (Markdown):** exactly this structure:

## {today}

### 1. The Funny One
> "the humor item"
One line on when to deploy it.

### 2. Business Insight
**[source]:** the insight, sharpened + a Kiln application.

### 3. Deep Line
> "the philosophy quote" — Attribution
1-2 sentence reframe.

### 4. Thought Principle: [name]
2-3 sentences explaining the framework + Kiln application.

### 5. New Words & Terms
**Word1** — definition + usage example.
**Word2** — same.
**Word3** — same.

### 6. Contrarian Take
> "the contrarian line"
1-2 sentences on why it's right and how Ultan uses it.

### 7. Analogy
The analogy, written so it lands, + what it explains for The Kiln.

### 8. Story
The anecdote with its specifics (names, numbers, outcome) + the lesson.

### 9. Rule of Thumb
**The rule** — 1-2 sentences on how to apply it.

### 10. Stoic Closer
> "the stoic line" — Attribution
One sentence.

### 11. Daily Math: [concept]
Concept + business example + insight + today's exercise. Progress through this curriculum, doing the NEXT topic not yet covered in recent entries: Expected Value, Bayes' Theorem, Law of Large Numbers, Standard Deviation, Normal Distribution, Confidence Intervals, Regression to the Mean, Pareto Distribution, Conditional Probability, Monte Carlo, Markov Chains, Kelly Criterion.

**Section 2 (Plain text for audio):** the same content written for text-to-speech — spell out "number one" etc., no markdown symbols. Start with "Your daily learning and enrichment for [date in spoken form]." End with "That's your daily learning and enrichment. Go make it count."

RECENT EPISODES (for math continuity + so you don't repeat phrasing):
{recent_dle}

Now write today's episode. Output the markdown, then `===AUDIO===` on its own line, then the audio script."""
    return prompt, picks


def call_claude(prompt):
    """Generate via the Claude Code CLI in headless print mode (subscription auth)."""
    import subprocess
    import time

    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)  # force subscription login, not paid credits

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
            time.sleep(min(60, 5 * (2 ** (attempt - 1))))
            continue

        out = proc.stdout.strip()
        if proc.returncode == 0 and out:
            return out

        err = (proc.stderr.strip() or out or "no output")[:500]
        if attempt == max_attempts:
            raise RuntimeError(f"claude CLI failed (exit {proc.returncode}): {err}")
        print(f"CLI error (exit {proc.returncode}): {err} — retry {attempt}/{max_attempts}", file=sys.stderr)
        time.sleep(min(60, 5 * (2 ** (attempt - 1))))


def main():
    print(f"Generating DLE for {today}...")
    prompt, picks = build_prompt()
    result = call_claude(prompt)

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

    # Only record items as used after a successful generation.
    mark_used(picks)

    print(f"Markdown saved: {OUTPUT_TEXT} ({len(md_part)} chars)")
    print(f"Audio script saved: {OUTPUT_AUDIO_SCRIPT} ({len(audio_part)} chars)")
    n = sum(len(v) for v in picks.values())
    print(f"Segments used: {n} items across {len([v for v in picks.values() if v])} pools")


if __name__ == "__main__":
    main()
