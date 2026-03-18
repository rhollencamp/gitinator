"""Git server-side hook implementations."""

from gitinator.hooks.protect_default_branch import update_hook

_update_hooks = [update_hook]


def run_update_hooks(repo, refname, old_sha, new_sha):
    """Run all hooks in order; return the first rejection reason or None."""
    for hook in _update_hooks:
        result = hook(repo, refname, old_sha, new_sha)
        if result is not None:
            return result
    return None
