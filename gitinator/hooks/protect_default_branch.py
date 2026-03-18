"""Hook that protects the default branch from deletion and force pushes."""

_NULL_SHA = "0" * 40


def _is_ancestor(repo, old_sha, new_sha):
    """Return True if old_sha is an ancestor of (or equal to) new_sha."""
    from gitinator.models import GitObject
    from gitinator.git import parse_commit

    visited = set()
    queue = [new_sha]
    while queue:
        sha = queue.pop()
        if sha == old_sha:
            return True
        if sha in visited:
            continue
        visited.add(sha)
        try:
            obj = GitObject.objects.get(
                repository=repo, sha=sha, type=GitObject.Type.COMMIT
            )
        except GitObject.DoesNotExist:
            continue
        queue.extend(parse_commit(bytes(obj.data)).parents)
    return False


def update_hook(repo, refname, old_sha, new_sha):
    """Reject deletions and force pushes to the default branch."""
    if refname != f"refs/heads/{repo.default_branch}":
        return None
    if new_sha == _NULL_SHA:
        return "deletion of default branch is not allowed"
    if old_sha != _NULL_SHA and not _is_ancestor(repo, old_sha, new_sha):
        return "force push to default branch is not allowed"
    return None
