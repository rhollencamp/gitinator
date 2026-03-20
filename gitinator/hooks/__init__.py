"""Git server-side hook implementations."""

from gitinator.hooks.protect_default_branch import (
    update_hook as _protect_default_branch,
)
from gitinator.hooks.sync_config_repos import post_receive_hook
from gitinator.hooks.validate_config_repo import update_hook as _validate_config_repo

_update_hooks = [_protect_default_branch, _validate_config_repo]
_post_receive_hooks = [post_receive_hook]


def run_update_hooks(repo, refname, old_sha, new_sha):
    """Run all hooks in order; return the first rejection reason or None."""
    for hook in _update_hooks:
        result = hook(repo, refname, old_sha, new_sha)
        if result is not None:
            return result
    return None


def run_post_receive_hooks(repo, ref_updates):
    """Run all post-receive hooks after refs have been successfully written.

    ref_updates is a list of (old_sha, new_sha, refname) tuples for each
    successfully updated ref. Post-receive hooks are fire-and-forget: they
    cannot reject the push and any exceptions must be handled by the caller.
    """
    for hook in _post_receive_hooks:
        hook(repo, ref_updates)
