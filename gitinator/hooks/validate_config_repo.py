"""Update hook that validates commits pushed to the gitinator/config repository."""

import re

import yaml

from gitinator.config_sync import walk_tree
from gitinator.git import NULL_SHA, parse_commit

# Names used as group or repo path segments must start with an alphanumeric
# character and contain only alphanumeric characters, hyphens, underscores, or
# dots — no characters that require URL-encoding.
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")

# Files that the config repo is allowed to contain.
_ALLOWED_ROOT_FILES = {"config.yaml"}


def _validate_path(path):
    """Return an error string if path is not permitted in the config repo, else None."""
    parts = path.split("/")

    if len(parts) == 1:
        if parts[0] not in _ALLOWED_ROOT_FILES:
            return f"unexpected file at root: {path}"
        return None

    if parts[0] == "repos":
        # repos/{group}/{repo}/config.yaml is the only allowed form
        if len(parts) != 4 or parts[3] != "config.yaml":
            return f"unexpected path under repos/: {path}"
        group_name, repo_name = parts[1], parts[2]
        if group_name == "gitinator":
            return "group name 'gitinator' is reserved"
        if not _NAME_RE.match(group_name):
            return (
                f"group name {group_name!r} contains characters that are not URL-safe"
            )
        if not _NAME_RE.match(repo_name):
            return f"repo name {repo_name!r} contains characters that are not URL-safe"
        return None

    return f"unexpected path: {path}"


def update_hook(repo, refname, old_sha, new_sha):
    """Reject pushes to gitinator/config that contain invalid paths, names, or malformed config.yaml files."""
    if repo.group_name != "gitinator" or repo.name != "config":
        return None

    if new_sha == NULL_SHA:
        return None  # deletion handled by protect_default_branch

    from gitinator.models import GitObject

    try:
        commit_obj = GitObject.objects.get(
            repository=repo, sha=new_sha, type=GitObject.Type.COMMIT
        )
    except GitObject.DoesNotExist:
        return None  # object not yet stored; object-existence check will reject it

    commit = parse_commit(bytes(commit_obj.data))

    for path, blob_sha in walk_tree(repo, commit.tree):
        error = _validate_path(path)
        if error:
            return error

        parts = path.split("/")
        if len(parts) == 4 and parts[0] == "repos" and parts[3] == "config.yaml":
            blob_obj = GitObject.objects.get(
                repository=repo, sha=blob_sha, type=GitObject.Type.BLOB
            )
            raw = bytes(blob_obj.data)
            try:
                data = yaml.safe_load(raw)
            except yaml.YAMLError as exc:
                return f"invalid YAML in {path}: {exc}"
            if data is not None and not isinstance(data, dict):
                return f"{path}: expected a mapping, got {type(data).__name__}"
            if isinstance(data, dict):
                default_branch = data.get("default_branch")
                if default_branch is not None and not isinstance(default_branch, str):
                    return f"{path}: 'default_branch' must be a string"

    return None
