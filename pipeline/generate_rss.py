#!/usr/bin/python3
"""
Generate an RSS 2.0 podcast feed from MP3 files in the repo's audio/ folder.
Each episode gets show notes (the full DLE text) from the DLE Advice.md file.
"""

import os
import re
import json
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

# --- CONFIG ---
REPO_NAME = "xq7m-feed-archive"
GITHUB_USER = "ultor123"
# DLE_HOME = repo root in CI ($GITHUB_WORKSPACE); locally the feed repo lives at ~/dle/feed-archive
DLE_HOME = os.environ.get("DLE_HOME", os.path.expanduser("~/dle"))
REPO_DIR = os.environ.get("DLE_HOME", os.path.expanduser("~/dle/feed-archive"))
AUDIO_DIR = os.path.join(REPO_DIR, "audio")
FEED_PATH = os.path.join(REPO_DIR, "feed.xml")
DLE_FILE = os.path.join(DLE_HOME, "data/DLE_Advice.md")

BASE_URL = f"https://{GITHUB_USER}.github.io/{REPO_NAME}"
# Audio is served from GitHub Releases (CDN) so the git repo stays small.
AUDIO_BASE_URL = f"https://github.com/{GITHUB_USER}/{REPO_NAME}/releases/download/audio"

PODCAST_TITLE = "Daily Learning and Enrichment"
PODCAST_DESCRIPTION = "Daily insights, frameworks, soundbites, and math for the entrepreneur building The Kiln to 100k MRR."
PODCAST_AUTHOR = "Ultan Rourke"
PODCAST_EMAIL = "ultan@thekiln.com"


def parse_dle_entries(md_path):
    """Parse the DLE Advice.md file into a dict of {date: full_text}."""
    if not os.path.exists(md_path):
        return {}

    with open(md_path) as f:
        content = f.read()

    entries = {}
    # Split on date headers "## YYYY-MM-DD"
    sections = re.split(r'^## (\d{4}-\d{2}-\d{2})\s*$', content, flags=re.MULTILINE)

    # sections[0] is preamble, then alternates date, content, date, content...
    for i in range(1, len(sections), 2):
        date = sections[i]
        text = sections[i + 1].strip() if i + 1 < len(sections) else ""
        # Strip horizontal rules at end
        text = re.sub(r'\n+---\s*$', '', text)
        entries[date] = text

    return entries


def format_show_notes(text):
    """Convert markdown to simple HTML for podcast show notes."""
    if not text:
        return ""
    # Headers
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    # Bold
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    # Italic
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    # Block quotes
    html = re.sub(r'^> (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)
    # Horizontal rules
    html = re.sub(r'^---\s*$', r'<hr/>', html, flags=re.MULTILINE)
    # Paragraphs
    html = re.sub(r'\n\n+', r'</p><p>', html)
    html = f"<p>{html}</p>"
    return html


def get_audio_assets():
    """Return {filename: size} for every published MP3.

    Source of truth is the GitHub Release 'audio' (public API, no auth needed).
    Falls back to any local files in AUDIO_DIR (covers a just-generated episode
    that hasn't uploaded yet, and offline local runs)."""
    assets = {}
    api = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/releases/tags/audio"
    try:
        import urllib.request
        req = urllib.request.Request(api, headers={"User-Agent": "dle-rss"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        for a in data.get("assets", []):
            if a["name"].endswith(".mp3"):
                assets[a["name"]] = a.get("size", 0)
    except Exception as e:
        print(f"Release asset query failed ({e}); using local files only.")
    # Local files override/supplement (freshest sizes)
    if os.path.isdir(AUDIO_DIR):
        for f in os.listdir(AUDIO_DIR):
            if f.endswith(".mp3"):
                try:
                    assets[f] = os.path.getsize(os.path.join(AUDIO_DIR, f))
                except OSError:
                    assets.setdefault(f, 0)
    return assets


def build_feed():
    entries = parse_dle_entries(DLE_FILE)
    assets = get_audio_assets()
    mp3_files = sorted(assets.keys(), reverse=True)

    now_rfc822 = format_datetime(datetime.now(timezone.utc))

    items_xml = []
    for mp3 in mp3_files:
        # Extract date from filename: DLE-YYYY-MM-DD.mp3
        m = re.match(r'DLE-(\d{4}-\d{2}-\d{2})\.mp3', mp3)
        if not m:
            continue
        date_str = m.group(1)
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=6)
        pub_date = format_datetime(dt)

        file_size = assets.get(mp3, 0)

        title = f"DLE {date_str}"
        show_notes = entries.get(date_str, "")
        description_html = format_show_notes(show_notes) if show_notes else PODCAST_DESCRIPTION

        item = f"""    <item>
      <title>{escape(title)}</title>
      <description><![CDATA[{description_html}]]></description>
      <pubDate>{pub_date}</pubDate>
      <guid isPermaLink="false">dle-{date_str}</guid>
      <enclosure url="{AUDIO_BASE_URL}/{mp3}" length="{file_size}" type="audio/mpeg"/>
      <itunes:duration>00:05:00</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
      <itunes:image href="{BASE_URL}/cover.jpg"/>
    </item>"""
        items_xml.append(item)

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(PODCAST_TITLE)}</title>
    <link>{BASE_URL}</link>
    <atom:link href="{BASE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
    <description>{escape(PODCAST_DESCRIPTION)}</description>
    <language>en-us</language>
    <copyright>{escape(PODCAST_AUTHOR)}</copyright>
    <lastBuildDate>{now_rfc822}</lastBuildDate>
    <itunes:author>{escape(PODCAST_AUTHOR)}</itunes:author>
    <itunes:summary>{escape(PODCAST_DESCRIPTION)}</itunes:summary>
    <itunes:owner>
      <itunes:name>{escape(PODCAST_AUTHOR)}</itunes:name>
      <itunes:email>{escape(PODCAST_EMAIL)}</itunes:email>
    </itunes:owner>
    <itunes:explicit>false</itunes:explicit>
    <itunes:image href="{BASE_URL}/cover.jpg"/>
    <image>
      <url>{BASE_URL}/cover.jpg</url>
      <title>{escape(PODCAST_TITLE)}</title>
      <link>{BASE_URL}</link>
    </image>
    <itunes:category text="Business"/>
    <itunes:category text="Education"/>
{chr(10).join(items_xml)}
  </channel>
</rss>
"""

    with open(FEED_PATH, "w") as f:
        f.write(feed)

    print(f"Feed written: {FEED_PATH}")
    print(f"Episodes: {len(items_xml)}")
    print(f"Public URL will be: {BASE_URL}/feed.xml")


if __name__ == "__main__":
    build_feed()
