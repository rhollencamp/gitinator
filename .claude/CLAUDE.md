# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack

- Python 3.11.x, Django 5.2.x
- SQLite (location configurable via `DATA_DIR` env var)
- Gunicorn for production serving

## Commands

Use the Makefile for all common tasks:

| Command | Purpose |
|---------|---------|
| `make setup` | Create venv, install deps, run migrations, create admin superuser (admin/helloworld) |
| `make dev` | Run dev server with `DEBUG=true` |
| `make test` | Run all tests |
| `make lint` | Ruff check with auto-fix |
| `make format` | Ruff auto-format |
| `make pr` | Format check + lint + test (run before submitting PRs) |
| `make clean` | Remove cache, venv, and database |

Only activate the venv manually (`source venv/bin/activate`) for commands not covered by the Makefile.

To run a single test: `source venv/bin/activate && python manage.py test gitinator.tests.test_foo`

## Code Conventions

- Every Python file must have a module docstring.
- Add method/function docstrings when the purpose isn't self-evident from name and signature.
- Place imports at the top of the file. Deferred (inline) imports are only acceptable to avoid circular imports or defer a costly side-effect — add a comment explaining why when used.

## Architecture

Gitinator is a self-hosted Git server. It stores git objects in a Django/SQLite database, implements the Git Smart HTTP protocol from scratch, and provides a web UI for browsing repositories.

### Core Models (`gitinator/models.py`)

- **`Repo`** — repository metadata (`group_name`, `name`, `default_branch`)
- **`GitObject`** — git objects stored as binary (`type`: blob/tree/commit/tag, `sha`, `data`)
- **`GitRef`** — branches and tags, each pointing to a `GitObject`

### Git Protocol (`gitinator/views/git_smart_http_views.py`)

Implements Git Smart HTTP: `info/refs` (ref advertisement), `git-upload-pack` (clone/fetch), `git-receive-pack` (push). Protocol framing lives in `pktline.py`; object packing in `pack.py`; object serialization/parsing in `git.py`.

### Authentication (`gitinator/http_auth.py`)

Custom `BasicAuthMiddleware` parses HTTP Basic Auth headers and populates `request.user`. Inserted after Django's `AuthenticationMiddleware`.

### Server-Side Hooks (`gitinator/hooks/`)

`run_update_hooks()` runs before a ref is updated (can reject the push); `run_post_receive_hooks()` runs after a successful push. Hook modules:

- `protect_default_branch` — rejects deletion and force-pushes of the default branch
- `validate_config_repo` — enforces path rules for the `gitinator/config` repo
- `sync_config_repos` — triggers config-as-code sync on push to `gitinator/config`

### Config-as-Code (`gitinator/config_sync.py`, `gitinator/bootstrap.py`)

A special `gitinator/config` repository (created on first `post_migrate`) is the source of truth for repository configuration. YAML files at `repos/{group}/{repo}/config.yaml` define repos. Pushing to this repo's default branch automatically syncs the database via `sync_repos_from_config()`.

### Web UI (`gitinator/views/browse_views.py`)

`repo_landing` renders the root tree and README.md (if present). `browse` navigates the file tree and renders blobs or subtrees. Detects binary vs. text content.

### Tests (`gitinator/tests/`)

`factories.py` provides `make_repo()`, `make_git_object()`, `make_branch()`, and `make_repo_fixture()` (a fully-wired repo with blob/tree/commit/branch) for test setup.
