#!/usr/bin/env python3
"""
Migrate a Bluesky mute list to Mastodon mutes.

How it works:
  1. Logs into Bluesky, pulls your full mute list (app.bsky.graph.getMutes).
  2. For each muted account's handle (e.g. someuser.bsky.social), assumes
     it is reachable on the fediverse via Bridgy Fed as:
         someuser.bsky.social@bsky.brid.gy
     This only works for Bluesky accounts that are bridged (most active
     ones are, since Bridgy Fed auto-bridges by default unless the user
     opted out).
  3. Searches Mastodon for that bridged handle (resolve=true triggers a
     live webfinger lookup so the account gets created on your instance
     if it doesn't exist there yet).
  4. Mutes the resulting account ID via the Mastodon API.

Progress is written to mute_migration_log.csv as it goes, and accounts
already logged as "muted" are skipped on re-runs, so it's safe to stop
and restart.

Requirements:
  pip install requests --break-system-packages

Credentials needed (do NOT hardcode — pass via environment variables):
  BSKY_HANDLE       your Bluesky handle, e.g. someuser.bsky.social
  BSKY_APP_PASSWORD an app password from Bluesky Settings > App Passwords
                     (NOT your main account password)
  MASTODON_INSTANCE your instance URL, e.g. https://mastodon.social
  MASTODON_TOKEN    an access token for your instance with scopes
                     read:accounts and write:mutes. Create one at
                     <your instance>/settings/applications/new

Usage:
  export BSKY_HANDLE=someuser.bsky.social
  export BSKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
  export MASTODON_INSTANCE=https://mastodon.social
  export MASTODON_TOKEN=your_token_here
  python3 bsky_to_mastodon_mutes.py            # dry run by default
  python3 bsky_to_mastodon_mutes.py --live     # actually mutes on Mastodon
"""

import csv
import os
import sys
import time
import argparse
import requests

BSKY_BASE = "https://bsky.social/xrpc"
LOG_FILE = "mute_migration_log.csv"
REQUEST_DELAY = 0.5  # seconds between Mastodon calls, be polite to the instance


def bsky_login(handle, app_password):
    r = requests.post(
        f"{BSKY_BASE}/com.atproto.server.createSession",
        json={"identifier": handle, "password": app_password},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    return data["accessJwt"]


def bsky_get_all_mutes(access_jwt):
    mutes = []
    cursor = None
    headers = {"Authorization": f"Bearer {access_jwt}"}
    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(
            f"{BSKY_BASE}/app.bsky.graph.getMutes",
            headers=headers,
            params=params,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        mutes.extend(data.get("mutes", []))
        cursor = data.get("cursor")
        if not cursor:
            break
    return mutes


def load_log():
    done = {}
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done[row["bsky_handle"]] = row["status"]
    return done


def append_log(row):
    is_new = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["bsky_handle", "bridged_handle", "status", "detail"])
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def mastodon_search_account(bridged_handle, token, instance):
    r = requests.get(
        f"{instance}/api/v1/accounts/search",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": bridged_handle, "resolve": "true", "limit": 5},
        timeout=20,
    )
    if r.status_code != 200:
        return None, f"search HTTP {r.status_code}: {r.text[:200]}"
    results = r.json()
    for acct in results:
        full = f"{acct.get('username')}@{acct.get('acct', '').split('@')[-1]}" if "@" in acct.get("acct", "") else acct.get("acct")
        if acct.get("acct", "").lower() == bridged_handle.lower() or acct.get("acct", "").lower() == bridged_handle.split("@")[0].lower():
            return acct["id"], None
    if results:
        # fall back to first result if search matched something close
        return results[0]["id"], None
    return None, "no account found"


def mastodon_mute_account(account_id, token, instance):
    r = requests.post(
        f"{instance}/api/v1/accounts/{account_id}/mute",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    if r.status_code != 200:
        return False, f"mute HTTP {r.status_code}: {r.text[:200]}"
    return True, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Actually mute on Mastodon. Without this flag, does a dry run.")
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

    print("Fetching mute list...")
    mutes = bsky_get_all_mutes(jwt)
    print(f"Found {len(mutes)} muted accounts on Bluesky.")

    done = load_log()

    for m in mutes:
        handle = m.get("handle")
        if not handle or handle == "handle.invalid":
            append_log({"bsky_handle": handle or "(unknown)", "bridged_handle": "", "status": "skipped", "detail": "no resolvable handle"})
            continue

        if done.get(handle) == "muted":
            print(f"  [skip] {handle} already muted")
            continue

        bridged_handle = f"{handle}@bsky.brid.gy"

        if not args.live:
            print(f"  [dry-run] would search + mute {bridged_handle}")
            continue

        account_id, err = mastodon_search_account(bridged_handle, mastodon_token, mastodon_instance)
        time.sleep(REQUEST_DELAY)

        if not account_id:
            print(f"  [fail] {handle}: {err}")
            append_log({"bsky_handle": handle, "bridged_handle": bridged_handle, "status": "not_found", "detail": err})
            continue

        ok, err = mastodon_mute_account(account_id, mastodon_token, mastodon_instance)
        time.sleep(REQUEST_DELAY)

        if ok:
            print(f"  [muted] {handle} -> {bridged_handle}")
            append_log({"bsky_handle": handle, "bridged_handle": bridged_handle, "status": "muted", "detail": ""})
        else:
            print(f"  [fail] {handle}: {err}")
            append_log({"bsky_handle": handle, "bridged_handle": bridged_handle, "status": "mute_failed", "detail": err})

    if not args.live:
        print("\nDry run complete. Re-run with --live to actually mute accounts on Mastodon.")
    else:
        print(f"\nDone. See {LOG_FILE} for full results.")


if __name__ == "__main__":
    main()
