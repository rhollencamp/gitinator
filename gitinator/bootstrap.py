"""Startup initialization logic for gitinator infrastructure repos."""

import time

from gitinator.git import TreeEntry, build_blob, build_commit, build_tree

_CONFIG_YAML = """\
# Gitinator configuration
# Add application config keys here.
"""


def ensure_config_repo(**kwargs):
    """Create the gitinator/config repo with an initial commit if it doesn't exist.

    Intended to be called from the post_migrate signal so the database is
    guaranteed to be fully set up before any writes occur.
    """
    # Deferred so this module remains importable before the Django app registry
    # is ready; models must not be imported until the registry is fully set up.
    from gitinator.models import GitObject, GitRef, Repo

    if Repo.objects.filter(group_name="gitinator", name="config").exists():
        return

    repo = Repo.objects.create(
        group_name="gitinator", name="config", default_branch="main"
    )

    blob_sha, blob_data = build_blob(_CONFIG_YAML.encode())
    GitObject.objects.create(
        repository=repo, sha=blob_sha, type=GitObject.Type.BLOB, data=blob_data
    )

    tree_sha, tree_data = build_tree(
        [TreeEntry(name="config.yaml", sha=blob_sha, mode="100644")]
    )
    GitObject.objects.create(
        repository=repo, sha=tree_sha, type=GitObject.Type.TREE, data=tree_data
    )

    now = f"Gitinator <gitinator@thewaffleshop.net> {int(time.time())} +0000"
    commit_sha, commit_data = build_commit(
        tree_sha=tree_sha,
        message="Initial commit\n",
        author=now,
        committer=now,
    )
    commit = GitObject.objects.create(
        repository=repo, sha=commit_sha, type=GitObject.Type.COMMIT, data=commit_data
    )

    GitRef.objects.create(
        repository=repo, name="main", type=GitRef.Type.BRANCH, git_object=commit
    )
