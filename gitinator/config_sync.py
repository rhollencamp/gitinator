"""Sync system state from the gitinator/config repository."""

import logging

import yaml

from gitinator.git import parse_commit, parse_tree

logger = logging.getLogger(__name__)


def _read_blob(config_repo, sha):
    """Return raw bytes for a blob object in config_repo."""
    from gitinator.models import GitObject

    obj = GitObject.objects.get(
        repository=config_repo, sha=sha, type=GitObject.Type.BLOB
    )
    return bytes(obj.data)


def walk_tree(repo, tree_sha, prefix=""):
    """Yield (path, blob_sha) for every blob reachable from tree_sha.

    Recurses into subtrees, building a slash-separated path from the root.
    """
    from gitinator.models import GitObject

    tree_obj = GitObject.objects.get(
        repository=repo, sha=tree_sha, type=GitObject.Type.TREE
    )
    for entry in parse_tree(bytes(tree_obj.data)):
        path = f"{prefix}{entry.name}" if prefix else entry.name
        if entry.type == "tree":
            yield from walk_tree(repo, entry.sha, prefix=f"{path}/")
        else:
            yield path, entry.sha


def sync_repos_from_config(config_repo):
    """Read the HEAD commit of config_repo and upsert Repo objects.

    Scans the tree for files matching repos/{group}/{repo}/config.yaml.
    Repos already in the database but absent from the config are left alone.
    """
    from gitinator.models import GitRef, Repo

    try:
        ref = GitRef.objects.select_related("git_object").get(
            repository=config_repo,
            name=config_repo.default_branch,
            type=GitRef.Type.BRANCH,
        )
    except GitRef.DoesNotExist:
        logger.warning("config repo has no default branch ref; skipping sync")
        return

    commit_data = parse_commit(bytes(ref.git_object.data))

    for path, blob_sha in walk_tree(config_repo, commit_data.tree):
        parts = path.split("/")
        # Expect exactly: repos / {group} / {repo} / config.yaml
        if len(parts) != 4 or parts[0] != "repos" or parts[3] != "config.yaml":
            continue
        group_name, repo_name = parts[1], parts[2]
        if not group_name or not repo_name:
            continue
        if group_name == "gitinator" and repo_name == "config":
            continue

        try:
            raw = _read_blob(config_repo, blob_sha)
            data = yaml.safe_load(raw)
        except Exception:
            logger.exception("Failed to parse %s; skipping", path)
            continue

        _defaults = {"default_branch": "main"}
        if data is None:
            data = _defaults
        elif not isinstance(data, dict):
            logger.warning("Expected a mapping in %s; skipping", path)
            continue
        else:
            data = {**_defaults, **data}

        default_branch = data["default_branch"]
        if not isinstance(default_branch, str):
            logger.warning("Invalid default_branch in %s; skipping", path)
            continue

        repo, created = Repo.objects.update_or_create(
            group_name=group_name,
            name=repo_name,
            defaults={"default_branch": default_branch},
        )
        action = "Created" if created else "Updated"
        logger.info(
            "%s repo %s/%s (default_branch=%s)",
            action,
            group_name,
            repo_name,
            default_branch,
        )
