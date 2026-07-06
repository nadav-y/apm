"""Stage-and-restore mechanism for ``apm update``'s plan-confirmation gate.

``download_callback`` (see ``resolve.py``) materialises a re-resolved
semver dep's new content to disk as part of *resolving* the dependency
graph -- this is unavoidable, since discovering a package's transitive
deps requires reading its manifest. But ``apm update`` shows the computed
plan and asks for confirmation only *after* resolve completes. Left alone,
that means a declined confirmation, a non-interactive abort (no TTY, no
``--yes``), or ``--dry-run`` all leave ``apm_modules/`` already advanced to
the new version while ``apm.lock.yaml`` stays on the old one.

This applies at any depth, not just to direct dependencies: a transitive
dependency's own semver range is force-re-evaluated against the remote too
(see ``APMDependencyResolver._should_force_recheck``), so a package several
levels deep can be about to get overwritten with no confirmation yet given.

This module closes that gap: ``backup_before_overwrite`` moves a dep's
existing install path aside (instead of letting the download/clone step
delete it outright) at the exact moment ``download_callback`` is about to
overwrite it, and ``restore_update_backups`` reconciles the outcome once
the plan-confirmation gate resolves -- discarding the backups on commit,
or restoring them (and removing any freshly-added content) otherwise.

Deliberately inline rather than a pre-pass that runs once before BFS
resolution starts: discovering a transitive dependency (e.g. a dep's own
dep) requires reading its parent's manifest first, so which paths need
backing up isn't fully known until resolution is already underway. Making
the backup decision at the moment each dependency is actually about to be
overwritten sidesteps that chicken-and-egg problem entirely -- it needs no
upfront knowledge of the tree shape.
"""

from __future__ import annotations

import hashlib
import re
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from apm_cli.utils.file_ops import robust_rmtree as _rrm

if TYPE_CHECKING:
    from apm_cli.install.context import InstallContext
    from apm_cli.models.dependency.reference import DependencyReference

# Short enough to keep backup directory names readable, long enough that an
# accidental collision between two sanitized-but-distinct dep keys is not a
# realistic concern.
_DISAMBIGUATOR_LEN = 8


def _sanitize_backup_name(dep_key: str) -> str:
    """Turn a dep key into a filesystem-safe, collision-resistant directory name.

    Sanitizing alone is not injective: ``"owner/repo"``, ``"owner_repo"``, and
    ``"owner:repo"`` would all collapse to the same ``"owner_repo"`` name,
    which risks one dep's backup silently overwriting another's (or restoring
    the wrong content). A short hash of the original, un-sanitized key is
    appended to keep distinct keys apart even after sanitization.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", dep_key)
    digest = hashlib.sha256(dep_key.encode("utf-8")).hexdigest()[:_DISAMBIGUATOR_LEN]
    return f"{safe}-{digest}"


def backup_before_overwrite(
    ctx: InstallContext,
    dep_ref: DependencyReference,
    install_path: Path,
) -> bool:
    """Move *install_path* aside before ``download_callback`` overwrites it.

    Called inline, immediately before the registry archive extraction or
    git clone/cache-copy that's about to replace an *existing* install
    path during a forced semver re-check (see
    ``APMDependencyResolver._should_force_recheck``). Applies uniformly at
    any depth -- a transitive dependency reached only because its parent's
    own re-check happened to run gets exactly the same protection as a
    direct one.

    No-ops (returns False) when there's nothing to protect against:
    ``install_path`` doesn't exist yet (a genuine first-time add -- nothing
    to back up, and ``restore_update_backups`` already removes an
    unbacked-up fresh add on decline), or ``ctx`` has no ``plan_callback``
    (``apm install --update`` has no decline path, so backing up would
    only add filesystem churn with nothing that ever reads it back).

    Raises on failure once staging is actually required (``plan_callback``
    is set and ``install_path`` exists). Swallowing the error here would
    let the caller proceed straight to overwriting ``install_path`` with
    no rollback point staged -- a later declined/aborted update would then
    see this dep in ``ctx.callback_downloaded`` but not ``ctx.update_backups``,
    indistinguishable from a fresh add, and delete it outright,
    permanently losing the original content. Raising instead surfaces to
    the ``resolve``-phase exception handler in ``pipeline.py``, which
    restores any backups already staged for other deps this run before
    re-raising -- the whole ``apm update`` aborts cleanly, which is
    recoverable; a silent, undetected loss of the original content is not.

    Returns True when a backup was actually staged, so the caller can
    log accordingly.
    """
    if not getattr(ctx, "plan_callback", None):
        return False
    if not install_path.exists():
        return False
    backup_root = ctx.apm_dir / ".apm-update-backup"
    dep_key = dep_ref.get_unique_key()
    backup_path = backup_root / _sanitize_backup_name(dep_key)
    if backup_path.exists():
        _rrm(backup_path, ignore_errors=True)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    install_path.rename(backup_path)
    if not isinstance(getattr(ctx, "update_backups", None), dict):
        ctx.update_backups = {}
    # The dep_ref is stored alongside the path (not just the path) so
    # restore_update_backups can compute get_install_path() directly,
    # without needing to look this dep up in all_apm_deps/
    # deps_to_install afterward. Those two lists are direct-only /
    # only-populated-on-success respectively -- a transitive dep
    # backed up here and then caught by a resolution failure elsewhere
    # (before deps_to_install is ever set) would otherwise be
    # unresolvable and its backup permanently orphaned.
    ctx.update_backups[dep_key] = (dep_ref, backup_path)
    return True


def restore_update_backups(ctx: InstallContext, *, keep_new: bool) -> None:
    """Reconcile ``ctx.update_backups`` after the plan-confirmation gate resolves.

    When *keep_new* is True (the update was confirmed and applied) AND the
    dep was actually re-downloaded this run, the fresh content stays in
    place and its backup is discarded. Every other backed-up dep -- either
    because *keep_new* is False (declined, non-interactive abort, or
    ``--dry-run``), or because it was staged but never actually
    re-resolved (e.g. a failure elsewhere aborted the run first) -- has
    its original content moved back into place. When not committing, a
    dep with no prior backup that was nonetheless downloaded this run (a
    fresh add swept up by this resolve pass) has its new content removed
    entirely. This is what keeps a declined/aborted/dry-run ``apm update``
    from silently leaving ``apm_modules/`` ahead of ``apm.lock.yaml``.

    ``ctx.update_backups`` maps ``dep_key -> (dep_ref, backup_path)`` --
    the dep_ref is captured at the moment ``backup_before_overwrite`` staged
    it, not looked up afterward via ``ctx.all_apm_deps`` /
    ``ctx.deps_to_install``. Those two lists are direct-only and
    only-populated-on-success respectively; a transitive dep backed up here
    and then caught by a resolution failure elsewhere (before
    ``deps_to_install`` is ever set) would otherwise be unresolvable and
    its backup permanently orphaned. The "remove a fresh add with no prior
    backup" pass below still needs a dep_ref for a *downloaded-but-not-
    backed-up* key, so it falls back to ``all_apm_deps`` merged with
    ``deps_to_install`` for that narrower case (a brand-new dependency,
    not one this module protected).
    """
    # Coerced with isinstance rather than a plain ``or {}`` fallback: a
    # loosely-mocked ctx (e.g. a bare MagicMock() in an unrelated pipeline
    # test) has these as auto-generated, always-truthy Mock attributes when
    # unset, which would otherwise slip past ``... or {}`` and break the
    # dict/list operations below.
    _raw_backups = getattr(ctx, "update_backups", None)
    backups: dict[str, tuple[DependencyReference, Path]] = (
        _raw_backups if isinstance(_raw_backups, dict) else {}
    )
    if not backups and keep_new:
        return
    _raw_downloaded = getattr(ctx, "callback_downloaded", None)
    downloaded = _raw_downloaded if isinstance(_raw_downloaded, dict) else {}
    _raw_all_deps = getattr(ctx, "all_apm_deps", None)
    _raw_deps_to_install = getattr(ctx, "deps_to_install", None)
    dep_by_key = {
        d.get_unique_key(): d for d in (_raw_all_deps if isinstance(_raw_all_deps, list) else [])
    }
    dep_by_key.update(
        {
            d.get_unique_key(): d
            for d in (_raw_deps_to_install if isinstance(_raw_deps_to_install, list) else [])
        }
    )
    apm_modules_dir = ctx.apm_modules_dir

    for _dep_key, _entry in backups.items():
        _dep, _backup_path = _entry
        if keep_new and _dep_key in downloaded:
            # New content committed -- the backup is no longer needed.
            with suppress(Exception):
                if _backup_path.exists():
                    _rrm(_backup_path, ignore_errors=True)
            continue
        # Not committed, or this dep was staged but never actually
        # re-resolved (e.g. an earlier failure aborted the run) -- restore
        # the original content.
        with suppress(Exception):
            _ip = _dep.get_install_path(apm_modules_dir)
            if _ip.exists():
                _rrm(_ip, ignore_errors=True)
            if _backup_path.exists():
                _ip.parent.mkdir(parents=True, exist_ok=True)
                _backup_path.rename(_ip)

    if not keep_new:
        # Freshly-downloaded deps with no prior backup (new adds swept into
        # this update pass) never existed before -- remove them outright.
        for _dep_key in downloaded:
            if _dep_key in backups:
                continue
            _dep = dep_by_key.get(_dep_key)
            if _dep is None:
                continue
            with suppress(Exception):
                _ip = _dep.get_install_path(apm_modules_dir)
                if _ip.exists():
                    _rrm(_ip, ignore_errors=True)

    if backups:
        _backup_root = next(iter(backups.values()))[1].parent
        with suppress(Exception):
            if _backup_root.is_dir() and not any(_backup_root.iterdir()):
                _backup_root.rmdir()
