"""Startup initialization logic for gitinator infrastructure repos."""

_GIT_AUTHOR = "Gitinator <gitinator@localhost> 0 +0000"

_CONFIG_YAML = """\
# Gitinator configuration
# Add application config keys here.
"""


def ensure_config_repo(**kwargs):
    """Create the gitinator/config repo with an initial commit if it doesn't exist.

    Intended to be called from the post_migrate signal so the database is
    guaranteed to be fully set up before any writes occur.
    """
    from gitinator.git import TreeEntry, build_blob, build_commit, build_tree
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

    commit_sha, commit_data = build_commit(
        tree_sha=tree_sha,
        message="Initial commit\n",
        author=_GIT_AUTHOR,
        committer=_GIT_AUTHOR,
    )
    commit = GitObject.objects.create(
        repository=repo, sha=commit_sha, type=GitObject.Type.COMMIT, data=commit_data
    )

    GitRef.objects.create(
        repository=repo, name="main", type=GitRef.Type.BRANCH, git_object=commit
    )
