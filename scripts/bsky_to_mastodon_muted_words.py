#!/usr/bin/env python3
"""
Migrate Bluesky muted words to Mastodon filters.

How it works:
  1. Logs into Bluesky, pulls app.bsky.actor.getPreferences, and finds
     the mutedWordsPref block (this is where Bluesky stores your
     Settings > Moderation > Muted words & tags list).
  2. For each muted word/tag, creates a Mastodon filter via the v2
     Filters API (POST /api/v2/filters) with a matching keyword.
     Filters are applied across home, notifications, public, thread,
     and profile contexts, action set to "hide" (closest equivalent
     to Bluesky's mute behaviour — content is removed rather than
     just flagged). Change FILTER_ACTION below to "warn" if you'd
     rather it just blur/warn instead of fully hide.

Progress is written to word_migration_log.csv as it goes, and words
already logged as "created" are skipped on re-runs.

Requirements:
  pip install requests --break-system-packages

Credentials needed (pass via environment variables, do NOT hardcode):
  BSKY_HANDLE       your Bluesky handle, e.g. someuser.bsky.social
  BSKY_APP_PASSWORD an app password from Bluesky Settings > App Passwords
  MASTODON_INSTANCE your instance URL, e.g. https://mastodon.social
  MASTODON_TOKEN    an access token for your instance with scopes
                     read:filters and write:filters

Usage:
  export BSKY_HANDLE=someuser.bsky.social
  export BSKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
  export MASTODON_INSTANCE=https://mastodon.social
  export MASTODON_TOKEN=your_token_here
  python3 bsky_to_mastodon_muted_words.py            # dry run by default
  python3 bsky_to_mastodon_muted_words.py --live     # actually creates filters
"""

import csv
import os
import sys
import time
import argparse
import requests

BSKY_BASE = "https://bsky.social/xrpc"
LOG_FILE = "word_migration_log.csv"
REQUEST_DELAY = 0.5

FILTER_CONTEXT = ["home", "notifications", "public", "thread", "account"]
FILTER_ACTION = "hide"  # or "warn"


def bsky_login(handle, app_password):
    r = requests.post(
        f"{BSKY_BASE}/com.atproto.server.createSession",
        json={"identifier": handle, "password": app_password},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["accessJwt"]


def bsky_get_muted_words(access_jwt):
    r = requests.get(
        f"{BSKY_BASE}/app.bsky.actor.getPreferences",
        headers={"Authorization": f"Bearer {access_jwt}"},
        timeout=15,
    )
    r.raise_for_status()
    prefs = r.json().get("preferences", [])
    for p in prefs:
        if p.get("$type") == "app.bsky.actor.defs#mutedWordsPref":
            return p.get("items", [])
    return []


def load_log():
    done = {}
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done[row["word"]] = row["status"]
    return done


def append_log(row):
    is_new = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["word", "status", "detail"])
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def mastodon_create_filter(word, token, instance):
    payload = {
        "title": word[:100],
        "context": FILTER_CONTEXT,
        "filter_action": FILTER_ACTION,
        "keywords_attributes": [{"keyword": word, "whole_word": "false"}],
    }
    r = requests.post(
        f"{instance}/api/v2/filters",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=20,
    )
    if r.status_code not in (200, 201):
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    return True, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Actually create filters on Mastodon. Without this flag, does a dry run.")
    args = parser.parse_args()

    bsky_handle = os.environ.get("BSKY_HANDLE")
    bsky_pw = os.environ.get("BSKY_APP_PASSWORD")
    mastodon_token = os.environ.get("MASTODON_TOKEN")
    mastodon_instance = os.environ.get("MASTODON_INSTANCE")

    if not all([bsky_handle, bsky_pw, mastodon_token, mastodon_instance]):
        print("Missing credentials. Set BSKY_HANDLE, BSKY_APP_PASSWORD, MASTODON_TOKEN, MASTODON_INSTANCE as environment variables.")
        sys.exit(1)

    mastodon_instance = mastodon_instance.rstrip("/")

    print(f"Logging into Bluesky as {bsky_handle}...")
    jwt = bsky_login(bsky_handle, bsky_pw)

    print("Fetching muted words...")
    items = bsky_get_muted_words(jwt)
    print(f"Found {len(items)} muted words/tags on Bluesky.")

    done = load_log()

    for item in items:
        word = item.get("value")
        if not word:
            continue

        if done.get(word) == "created":
            print(f"  [skip] '{word}' already created")
            continue

        if not args.live:
            print(f"  [dry-run] would create filter for '{word}'")
            continue

        ok, err = mastodon_create_filter(word, mastodon_token, mastodon_instance)
        time.sleep(REQUEST_DELAY)

        if ok:
            print(f"  [created] '{word}'")
            append_log({"word": word, "status": "created", "detail": ""})
        else:
            print(f"  [fail] '{word}': {err}")
            append_log({"word": word, "status": "failed", "detail": err})

    if not args.live:
        print("\nDry run complete. Re-run with --live to actually create filters on Mastodon.")
    else:
        print(f"\nDone. See {LOG_FILE} for full results.")


if __name__ == "__main__":
    main()
