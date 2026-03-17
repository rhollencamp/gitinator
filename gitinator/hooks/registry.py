"""Registry for git server-side update hooks."""

_update_hooks: list = []


def register_update_hook(hook):
    """Register a callable as an update hook.

    The hook must accept (repo, refname, old_sha, new_sha) and return None to
    approve or a string rejection reason to deny.
    """
    _update_hooks.append(hook)


def run_update_hooks(repo, refname, old_sha, new_sha):
    """Run all registered update hooks in order.

    Returns None if all hooks approve, or the first rejection reason string.
    """
    for hook in _update_hooks:
        result = hook(repo, refname, old_sha, new_sha)
        if result is not None:
            return result
    return None
