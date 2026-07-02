# bsky-to-mastodon-muting

Two small scripts for carrying your moderation setup from Bluesky over to Mastodon:

- **`scripts/bsky_to_mastodon_mutes.py`** — migrates the accounts you've muted on Bluesky.
- **`scripts/bsky_to_mastodon_muted_words.py`** — migrates your muted words/tags from Bluesky's Settings > Moderation > Muted words & tags.

Neither platform has a native import/export for this, and no bridging tool (Bridgy Fed, Bounce, etc.) carries moderation lists across — only identity and posts. These scripts fill that gap.

## How it works

### Muted accounts

Bluesky and Mastodon run on incompatible protocols (AT Protocol vs ActivityPub), so a muted Bluesky account has no native Mastodon equivalent to mute directly. This script relies on [Bridgy Fed](https://fed.brid.gy/), which auto-bridges most active Bluesky accounts to the fediverse under the handle:

```
someuser.bsky.social@bsky.brid.gy
```

For each account in your Bluesky mute list, the script searches Mastodon for that bridged handle and mutes it if found.

**Limitation:** this only catches Bluesky accounts that are actually bridged. Anyone who's opted out of Bridgy Fed won't have a fediverse presence to mute — the script will log those as `not_found`.

### Muted words

Fetches your muted words/tags from Bluesky's preferences (`app.bsky.actor.getPreferences`) and recreates each one as a keyword [Filter](https://docs.joinmastodon.org/methods/filters/) on Mastodon (`POST /api/v2/filters`), applied across all contexts (home, notifications, public, thread, profile).

Default filter action is `hide` (closest match to Bluesky's mute behaviour, which removes content rather than just flagging it). Change `FILTER_ACTION` to `"warn"` in the script if you'd rather have posts blurred/warned instead.

## Setup

```bash
git clone https://github.com/<you>/bsky-to-mastodon-muting.git
cd bsky-to-mastodon-muting
pip install -r requirements.txt
```

### Credentials

Both scripts read credentials from environment variables — nothing is hardcoded, nothing gets written to disk except the CSV log.

| Variable | What it is |
|---|---|
| `BSKY_HANDLE` | Your Bluesky handle, e.g. `someuser.bsky.social` |
| `BSKY_APP_PASSWORD` | An [app password](https://bsky.app/settings/app-passwords) — **not** your main Bluesky password |
| `MASTODON_INSTANCE` | Your instance URL, e.g. `https://mastodon.social` |
| `MASTODON_TOKEN` | An access token created at `<your instance>/settings/applications/new` |

Token scopes needed:
- For muted accounts: `read:accounts`, `write:mutes`
- For muted words: `read:filters`, `write:filters`

You can create one application with all four scopes if you want a single token for both scripts.

## Usage

Both scripts default to a **dry run** — they'll tell you what they'd do without making changes. Add `--live` to actually execute.

```bash
export BSKY_HANDLE=someuser.bsky.social
export BSKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
export MASTODON_INSTANCE=https://mastodon.social
export MASTODON_TOKEN=your_token_here

# muted accounts
python3 scripts/bsky_to_mastodon_mutes.py            # dry run
python3 scripts/bsky_to_mastodon_mutes.py --live     # actually mutes

# muted words
python3 scripts/bsky_to_mastodon_muted_words.py            # dry run
python3 scripts/bsky_to_mastodon_muted_words.py --live     # actually creates filters
```

Each run writes a CSV log (`mute_migration_log.csv` / `word_migration_log.csv`) in the working directory. Re-running with `--live` skips anything already logged as done, so it's safe to stop and resume — useful if you're migrating a large list and hit a rate limit partway through.

## Rate limiting

Both scripts sleep 0.5s between Mastodon API calls. If your instance has tighter rate limits, increase `REQUEST_DELAY` at the top of the script.

## License

MIT — see [LICENSE](LICENSE).
