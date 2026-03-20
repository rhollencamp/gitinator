# Config Repo

The config repo (`gitinator/config`) is a special git repository that controls
system-wide configuration. Operators manage gitinator by pushing commits to this
repo using standard git tooling — no admin UI or CLI commands are required.

## Location and access

The config repo is always available at the path `gitinator/config`. It is created
automatically on first startup (via the `post_migrate` signal) with an initial
commit. Like any other repo hosted by gitinator, it is accessible over the
standard smart HTTP protocol:

```
git clone http://<host>/repos/gitinator/config
```

## Structure

The repository tree is strictly validated — only the following paths may be
committed:

| Path | Purpose |
|------|---------|
| `config.yaml` | Top-level application settings (reserved for future use) |
| `repos/{group}/{repo}/config.yaml` | Definition of a hosted repository |

Committing any other file, or using an invalid naming convention, is rejected
by a server-side update hook before the push is accepted.

### Naming rules for `{group}` and `{repo}`

Group and repository names:

- Must start with an alphanumeric character (`a–z`, `A–Z`, `0–9`)
- May contain alphanumeric characters, hyphens (`-`), underscores (`_`), and
  dots (`.`)
- Must not use the reserved group name `gitinator`

The reserved group ensures system repositories cannot be accidentally (or
maliciously) redefined through the config repo itself.

## Repository definitions

Each file at `repos/{group}/{repo}/config.yaml` declares one hosted repository.
The directory layout — rather than a field inside the file — is the canonical
source of the group and repository name.

### Schema

```yaml
default_branch: main   # optional; name of the default branch (default: "main")
```

Additional fields will be added as new features are specified.

### Sync behavior

When a push to the config repo's default branch is accepted, gitinator reads
the new tree and upserts every repository definition it finds:

- **Create**: a `repos/{group}/{repo}/config.yaml` entry whose group/repo does
  not yet exist in the database causes a new repository to be created.
- **Update**: if the repository already exists, its settings (e.g.
  `default_branch`) are updated to match the file.
- **Empty file**: an empty `repos/{group}/{repo}/config.yaml` is valid and
  creates or updates the repository using all default values.
- **No auto-delete**: removing a `repos/{group}/{repo}/config.yaml` entry from
  the config repo does **not** delete the repository or its git history. Deletion
  must be performed through other means (to be specified).

Sync only runs when the config repo's default branch is updated. Pushes to
other branches are validated but do not trigger a sync.

## Validation

The following constraints are enforced at push time by a server-side update hook:

1. All file paths must match the allowed structure (see table above).
2. Group and repository names must conform to the naming rules above.
3. The group name `gitinator` is reserved and may not be used.

Invalid pushes are rejected before any refs are written; the git client receives
a descriptive error message identifying which rule was violated.

## Relationship to other hooks

The config repo is subject to the same hooks as all other repositories:

- **protect-default-branch**: the default branch (`main`) cannot be deleted or
  force-pushed.
- **validate-config-repo**: enforces the path and naming rules described above
  (config repo only).

The post-receive sync runs after both update hooks have approved the push.
