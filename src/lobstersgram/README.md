# Lobstersgram

Lobstersgram publishes new [Lobsters](https://lobste.rs/) stories to Telegram
with a readable Telegraph page, a link to the original article, and a link to
the discussion. It runs as a scheduled command, so it does not need a server
or a continuously running bot process.

The application reuses [`markdown-this`](../../packages/markdown-this) to
extract article content and [`md-to-telegraph`](../../packages/md-to-telegraph)
to publish it.

Subscribe to the [@lobstersgram Telegram channel](https://t.me/lobstersgram).

## Requirements

- Python 3.12+
- A Telegram bot token with permission to post in the destination channel
- A Telegraph access token

Set these environment variables (a local `.env` file is supported):

```dotenv
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHANNEL_ID=@your_channel
TELEGRAPH_ACCESS_TOKEN=...
```

`TELEGRAM_DEV_CHAT_ID` is optional. When set, it sends posts to that chat
instead of the channel, which is useful for local checks.

## Run

From the workspace root, install dependencies and inspect the available
options:

```bash
uv sync
uv run lobstersgram --help
```

The default command fetches the Lobsters RSS feed, skips items already present
in `state.json`, creates Telegraph pages, and posts new stories. Other useful
commands:

```bash
uv run lobstersgram --url https://example.com/article
uv run lobstersgram --sync-updates
uv run lobstersgram publish-to-telegraph https://example.com/article
```

`--url` posts one URL to Telegram. `--sync-updates` records current Telegram
reactions as bookmarks. `publish-to-telegraph` creates Telegraph pages and
prints their URLs without sending Telegram messages. The legacy
`--read-messages` and `send-migration-message` commands are also available.

## Configuration and state

The CLI accepts overrides for the RSS URL, state file paths, maximum items per
run, request timeout, log level, retry counts, and inter-message delay. Run
`uv run lobstersgram --help` for the full list.

By default, the application reads and writes `state.json`,
`message_map.json`, `bookmark.csv`, and `subscribers.json` in the current
directory. Keep these files between runs: they track processed stories,
Telegram messages, reactions, and legacy subscribers.

The repository's [scheduled workflow](../../.github/workflows/lobsters.yml)
runs every two hours and commits updated state files.

## Development

```bash
uv run pytest -q
uv run ruff check src/lobstersgram tests
```

See the [Lobstersgram documentation](../../docs/lobstersgram/overview.md)
for the architecture and technical reference.
