# Gitinator

A self-hosted Git server with a focus on GitOps and config as code. Repositories are defined and managed by pushing a YAML configuration to a special config repository — no admin UI required.

## Features

- **Git Smart HTTP** — clone, push, and pull with any standard git client
- **Config as code** — declare repositories in YAML, push to apply
- **Web UI** — browse repository file trees and READMEs
- **Server-side hooks** — protect default branches, validate config structure
- **HTTP Basic Auth** — push access restricted to staff users

## Getting Started

```bash
make setup   # create venv, install deps, run migrations, create admin user
make dev     # start development server at http://localhost:8000
```

The default admin credentials are `admin` / `helloworld`. Change them before deploying.

## Managing Repositories

Gitinator creates a special `gitinator/config` repository on first startup. Push configuration there to create and update repositories.

**Repository layout:**

```
repos/
  {group}/
    {repo}/
      config.yaml
```

**`repos/{group}/{repo}/config.yaml`:**

```yaml
default_branch: main  # optional, defaults to "main"
```

The file may also be empty to accept all defaults. When the config repo's default branch is updated, Gitinator reads the tree and creates or updates the declared repositories automatically. Removing an entry does not delete the repository.

**Clone the config repo and add a repository:**

```bash
git clone http://localhost:8000/repos/gitinator/config
mkdir -p repos/myorg/myrepo
echo "default_branch: main" > repos/myorg/myrepo/config.yaml
git add .
git commit -m "add myrepo"
git push
```

`myorg/myrepo` is now available at `http://localhost:8000/repos/myorg/myrepo/`.

### Naming Rules

Group and repository names must start with an alphanumeric character and contain only letters, digits, hyphens, underscores, and dots. The group name `gitinator` is reserved.

## Development

```bash
make test    # run test suite
make lint    # lint with ruff
make format  # format with ruff
make pr      # format check + lint + tests (run before opening a PR)
```

## License

MIT
