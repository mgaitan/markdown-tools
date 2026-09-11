# Working with This Workspace

Lobstersgram is a uv-managed Python workspace. Keep changes small, preserve the
boundaries between the application and reusable packages, and run the checks
that cover the code you touched.

This file is adapted from the [python-package-copier-template AGENTS.md](https://github.com/mgaitan/python-package-copier-template/blob/main/AGENTS.md).

## Workspace Layout

- `src/lobstersgram/` contains the main Telegram application and its
  `lobstersgram` command-line entrypoint.
- `packages/md-to-telegraph/` contains the reusable Markdown-to-Telegraph
  package.
- `packages/markdown-this/` contains the reusable URL/HTML-to-Markdown
  package.
- Each child package has its own `pyproject.toml`, metadata, dependencies,
  version, `README.md`, `src/<import_name>/`, and package-local tests.
- The root `pyproject.toml` owns workspace membership and shared Ruff, pytest,
  and coverage configuration. `uv.lock` is shared by the workspace.
- Root `tests/` covers the application; tests for a reusable package belong in
  that package's `tests/` directory.

## Common Commands

```bash
uv sync
uv run lobstersgram --help
uv run pytest -q
uv run pytest packages/markdown-this/tests/test_html.py
uv run ruff check .
uv run ruff format --check .
uv build --all-packages
```

The default coverage gate measures `md_to_telegraph` and `markdown_this` at
100%. The application tests run in the same pytest invocation, but the root
configuration does not currently enforce 100% coverage for `lobstersgram`.

## Package Boundaries

- Keep Telegram orchestration, configuration, persistence, and runtime state
  in `src/lobstersgram/`.
- Keep reusable conversion and extraction logic in the relevant child package.
- Reusable packages should not import application modules from `lobstersgram`.
- Put shared QA configuration in the root `pyproject.toml`; keep package
  metadata and package-specific runtime dependencies in the child package's
  `pyproject.toml`.

## Cost-Conscious Integrations

- Prioritize local, open-source, browser-native, and free-tier capabilities.
- Before introducing a paid API, API credential, or metered dependency, verify
  its cost and look for a free approach using tools already available in the
  workspace. Ask for explicit approval before choosing a paid path.
- Keep a no-cost fallback when an optional external integration is unavailable.

## Releases

Packages are versioned and released independently. Bump a package from the
workspace root, for example:

```bash
uv version --package markdown-this --bump patch
uv lock
git tag markdown-this-v<version>
git push origin markdown-this-v<version>
```

The reusable packages are published independently. Each publishing workflow
is dedicated to one package: `publish-md-to-telegraph.yml` publishes
`md-to-telegraph`, and `publish-markdown-this.yml` publishes `markdown-this`.
The `lobstersgram` application is not published to PyPI yet. A release tag only
activates the matching workflow.

## Editing and Verification

- Use `apply_patch` for manual edits.
- Do not manually edit `uv.lock`; regenerate it with `uv lock` after dependency
  or version changes.
- Do not overwrite runtime state files such as `state.json`, subscribers,
  message maps, or bookmarks unless the task explicitly requires it.
- Never discard unrelated user changes with destructive git commands.
- Before handing off a change, run the narrowest useful tests plus `ruff check`;
  for dependency, packaging, or workspace changes also run `uv build --all-packages`.
