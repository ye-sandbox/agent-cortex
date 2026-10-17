"""Git repository drift scanner and diff inspection utilities."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from cortex.ingestion.models import FileChange, FileChangeType, GitDriftSummary

logger = logging.getLogger(__name__)


class GitCommandError(RuntimeError):
    """Raised when an underlying git command fails."""

    def __init__(self, command: list[str], returncode: int, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        cmd_str = " ".join(command)
        super().__init__(f"Git command failed ({returncode}): '{cmd_str}'\n{stderr}")


def run_git(repo_path: Path | str, args: list[str], check: bool = True) -> str:
    """Execute git command within target repository and return stdout stripped."""
    p = Path(repo_path).resolve()
    full_cmd = ["git", *args]
    res = subprocess.run(  # noqa: S603
        full_cmd,
        cwd=p,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and res.returncode != 0:
        raise GitCommandError(full_cmd, res.returncode, res.stderr.strip())
    return res.stdout.strip()


def run_git_bytes(repo_path: Path | str, args: list[str], check: bool = True) -> bytes:
    """Execute git command within target repository and return raw bytes stdout."""
    p = Path(repo_path).resolve()
    full_cmd = ["git", *args]
    res = subprocess.run(  # noqa: S603
        full_cmd,
        cwd=p,
        capture_output=True,
        check=False,
    )
    if check and res.returncode != 0:
        err_msg = res.stderr.decode("utf-8", errors="replace").strip()
        raise GitCommandError(full_cmd, res.returncode, err_msg)
    return res.stdout


def is_git_repository(path: Path | str) -> bool:
    """Check if target path is inside a valid git repository worktree."""
    try:
        out = run_git(path, ["rev-parse", "--is-inside-work-tree"], check=False)
        return out == "true"
    except Exception:
        return False


def get_git_root(path: Path | str) -> Path:
    """Return top-level root directory of the git working tree."""
    p = Path(path).resolve()
    out = run_git(p, ["rev-parse", "--show-toplevel"])
    out_path = Path(out)
    if not out_path.is_absolute():
        return (p / out_path).resolve()
    return out_path.resolve()


def get_git_common_dir(path: Path | str) -> Path:
    """Return common git directory, identifying primary repo when inside a git worktree."""
    p = Path(path).resolve()
    out = run_git(p, ["rev-parse", "--git-common-dir"])
    out_path = Path(out)
    if not out_path.is_absolute():
        return (p / out_path).resolve()
    return out_path.resolve()


def get_head_commit(repo_path: Path | str) -> str:
    """Return current commit SHA of HEAD."""
    return run_git(repo_path, ["rev-parse", "HEAD"])


def resolve_commit_sha(repo_path: Path | str, ref: str) -> str:
    """Resolve a git ref or branch name to its full 40-character commit SHA."""
    return run_git(repo_path, ["rev-parse", f"{ref}^{{commit}}"])


def is_commit_valid(repo_path: Path | str, commit_sha: str) -> bool:
    """Check if commit SHA exists and is reachable in repository object database."""
    if not commit_sha or not commit_sha.strip():
        return False
    try:
        run_git(repo_path, ["cat-file", "-e", f"{commit_sha.strip()}^{{commit}}"])
        return True
    except GitCommandError:
        return False


def get_submodule_paths(repo_path: Path | str) -> set[str]:
    """Discover paths of all registered git submodules to avoid duplicate indexing."""
    try:
        raw_output = run_git_bytes(repo_path, ["ls-files", "--stage", "-z"], check=False)
        submodules: set[str] = set()
        entries = raw_output.split(b"\0")
        for entry in entries:
            if not entry:
                continue
            # Format: <mode> <sha> <stage>\t<path>
            parts = entry.split(b"\t", 1)
            if len(parts) == 2 and parts[0].startswith(b"160000 "):
                submodules.add(parts[1].decode("utf-8", errors="replace"))
        return submodules
    except Exception as exc:
        logger.debug("Failed to inspect submodules in %s: %s", repo_path, exc)
        return set()


def list_tracked_files(repo_path: Path | str) -> list[str]:
    """Return list of all tracked non-submodule files in the repository."""
    raw_output = run_git_bytes(repo_path, ["ls-files", "-z"])
    submodules = get_submodule_paths(repo_path)

    files: list[str] = []
    for item in raw_output.split(b"\0"):
        if not item:
            continue
        path_str = item.decode("utf-8", errors="replace")
        # Ignore files residing inside submodules
        if any(path_str == sm or path_str.startswith(f"{sm}/") for sm in submodules):
            continue
        files.append(path_str)

    return files


def scan_git_drift(
    repo_path: Path | str,
    base_commit: str | None = None,
    target_commit: str = "HEAD",
    repo_name: str | None = None,
) -> GitDriftSummary:
    """Scan git repository for file drift between base commit and target commit.

    If base_commit is None or unreachable, performs full working tree file enumeration
    treating all tracked files as ADDED.
    """
    path = Path(repo_path).resolve()
    resolved_repo_name = repo_name or path.name

    if not is_git_repository(path):
        msg = f"Path '{path}' is not a valid git repository."
        raise ValueError(msg)

    target_sha = resolve_commit_sha(path, target_commit)

    # Initial scan or invalid base commit -> scan all tracked files as ADDED
    if base_commit is None or not is_commit_valid(path, base_commit):
        tracked = list_tracked_files(path)
        initial_changes = [FileChange(change_type=FileChangeType.ADDED, path=f) for f in tracked]
        return GitDriftSummary(
            repo=resolved_repo_name,
            repo_path=path,
            base_commit=None,
            target_commit=target_sha,
            changes=initial_changes,
        )

    base_sha = resolve_commit_sha(path, base_commit)

    # No commit difference -> zero drift
    if base_sha == target_sha:
        return GitDriftSummary(
            repo=resolved_repo_name,
            repo_path=path,
            base_commit=base_sha,
            target_commit=target_sha,
            changes=[],
        )

    # Run git diff with rename and copy detection
    raw_diff = run_git_bytes(
        path,
        ["diff", "-z", "--name-status", "-M", "-C", base_sha, target_sha],
    )

    submodules = get_submodule_paths(path)
    tokens = [t.decode("utf-8", errors="replace") for t in raw_diff.split(b"\0") if t]

    changes: list[FileChange] = []
    idx = 0
    while idx < len(tokens):
        status_token = tokens[idx]
        idx += 1
        if not status_token:
            continue

        status_code = status_token[0]

        if status_code in ("R", "C"):
            if idx + 1 >= len(tokens):
                break
            old_path = tokens[idx]
            new_path = tokens[idx + 1]
            idx += 2

            # Skip submodules
            if any(new_path == sm or new_path.startswith(f"{sm}/") for sm in submodules):
                continue

            change_type = FileChangeType.RENAMED if status_code == "R" else FileChangeType.COPIED
            changes.append(FileChange(change_type=change_type, path=new_path, old_path=old_path))
        else:
            if idx >= len(tokens):
                break
            file_path = tokens[idx]
            idx += 1

            # Skip submodules
            if any(file_path == sm or file_path.startswith(f"{sm}/") for sm in submodules):
                continue

            if status_code == "A":
                changes.append(FileChange(change_type=FileChangeType.ADDED, path=file_path))
            elif status_code == "M" or status_code == "T":
                changes.append(FileChange(change_type=FileChangeType.MODIFIED, path=file_path))
            elif status_code == "D":
                changes.append(FileChange(change_type=FileChangeType.DELETED, path=file_path))
            else:
                logger.debug("Unhandled git diff status code '%s' for '%s'", status_code, file_path)

    return GitDriftSummary(
        repo=resolved_repo_name,
        repo_path=path,
        base_commit=base_sha,
        target_commit=target_sha,
        changes=changes,
    )
