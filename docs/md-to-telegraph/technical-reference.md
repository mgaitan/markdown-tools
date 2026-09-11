# Technical Reference

## Main Modules

- `md_to_telegraph.markdown`: front matter and Markdown helpers.
- `md_to_telegraph.md_to_dom`: Markdown AST to Telegraph DOM conversion.
- `md_to_telegraph.telegraph`: Telegraph API publishing.
- `md_to_telegraph.cli`: command-line entrypoint.

## Boundaries

This package should not fetch source articles or know about Telegram. It
accepts Markdown and publishes Telegraph pages.

Telegraph has no table node. Markdown tables are therefore preserved as their
original Markdown inside a `pre/code` block rather than being flattened or
sent as invalid Telegraph content.
