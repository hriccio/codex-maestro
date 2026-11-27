"""Singleton local Codex coordination and isolated worker launches."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import argparse
import sqlite3
import shutil
import subprocess
import sys
import uuid
from contextlib import contextmanager

from task_store import Store, add_parser, database_path, markdown


def runtime_root():
    return database_path().parent / "attempts"


def session_name():
    # Keep session identity stable per user and home directory.
    digest = hashlib.sha256(str(Path.home()).encode()).hexdigest()[:10]
    return f"codex-maestro-{os.getuid()}-{digest}"


@contextmanager
def locked(root=None):
    root = root or runtime_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield root


def run(*args, **kwargs):
    return subprocess.run(list(args), check=True, text=True, **kwargs)


def git(path, *args):
    return run("git", "-C", str(path), *args, capture_output=True).stdout.strip()


def alive(session):
    return subprocess.run(["tmux", "has-session", "-t", "=" + session],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def require(*commands):
    for command in commands:
        if shutil.which(command) is None:
            raise SystemExit(f"{command} is required")


def canonical_remote(value):
    match = re.fullmatch(r"(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?/?", value)
    if not match:
        raise SystemExit("expected a GitHub origin remote (SSH or HTTPS)")
    identity = match[1].lower()
    if any(part in {".", ".."} for part in identity.split("/")):
        raise SystemExit("invalid GitHub repository identity")
    return identity


def attach(session):
    if os.environ.get("TMUX"):
        return subprocess.call(["tmux", "switch-client", "-t", session])
    return subprocess.call(["tmux", "attach-session", "-t", session])


def save(path, record):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n")
    temporary.replace(path)


def worker_window(session, window):
    result = subprocess.run(["tmux", "list-windows", "-t", "=" + session, "-F", "#{window_id}"],
                            text=True, capture_output=True)
    return result.returncode == 0 and window in result.stdout.splitlines()


def status(_args):
    require("tmux")
    with locked() as root:
        for path in sorted(root.glob("*.json")):
            record = json.loads(path.read_text())
            if record["state"] == "launched" and not worker_window(record["session"], record.get("window", "")):
                record["state"] = "interrupted"
                save(path, record)
            print(json.dumps(record))
    return 0


def start(_args):
    require("tmux")
    session = session_name()
    with locked():
        if not alive(session):
            run("tmux", "new-session", "-d", "-s", session, "-n", "maestro")
    print(session)
    return 0


def attach_command(_args):
    require("tmux")
    if not alive(session_name()):
        raise ValueError("start Maestro before attaching")
    return attach(session_name())


def dispatch(args):
    require("tmux", "git", "codex")
    executable = os.path.abspath(shutil.which("codex"))
    repo = Path(args.checkout).expanduser().resolve()
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise ValueError("checkout must be a Git checkout root")
    identity = canonical_remote(git(repo, "remote", "get-url", "origin"))
    try:
        base = args.base or git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    except subprocess.CalledProcessError:
        raise ValueError("local origin/HEAD is missing; use --base REF") from None
    commit = git(repo, "rev-parse", "--verify", "--end-of-options", base + "^{commit}")
    session = session_name()
    with locked() as root:
        if not alive(session):
            raise ValueError("start Maestro before dispatching")
        store = Store()
        try:
            task = store.get(args.issue)
            if identity != task["repository"]:
                raise ValueError(f"repository mismatch: task expects {task['repository']}, origin is {identity}")
            path = root / f"{task['id']}.json"
            if path.exists():
                raise ValueError("task already has an attempt; inspect status and recover manually")
            task = store.claim(task["id"], args.revision, path)
        finally:
            store.close()
        attempt = f"{task['id']}-{uuid.uuid4().hex[:8]}"
        worktree = database_path().parent / "worktrees" / identity / attempt
        branch = f"codex/{attempt.lower()}"
        prompt_file = path.with_suffix(".prompt.txt")
        record = dict(task_snapshot=task, claim_token=task["claim"], session=session,
                      worktree=str(worktree), branch=branch, base=commit, model=args.model,
                      effort=args.effort, prompt_file=str(prompt_file), state="preparing")
        try:
            save(path, record)
            prompt_file.write_text("Follow the checkout's AGENTS.md. Report acceptance evidence and blockers.\n\n"
                                   + markdown(task), encoding="utf-8")
            worktree.parent.mkdir(parents=True, exist_ok=True)
            run("git", "-C", str(repo), "worktree", "add", "-b", branch, str(worktree), commit)
            result = run("tmux", "new-window", "-d", "-P", "-F", "#{window_id}", "-t", session + ":",
                         "-n", task["id"], "-c", str(worktree), sys.executable, "-B",
                         str(Path(__file__).resolve()), "_worker", str(path), executable, capture_output=True)
            record.update(state="launched", window=result.stdout.strip())
            save(path, record)
        except (OSError, subprocess.CalledProcessError) as exc:
            record.update(state="failed", error=type(exc).__name__)
            save(path, record)
            raise ValueError(f"dispatch failed; inspect recovery record at {path}") from exc
    print(worktree)
    return 0


def worker(path, executable):
    with locked(path.parent):
        record = json.loads(path.read_text())
    prompt = Path(record["prompt_file"]).read_text(encoding="utf-8")
    try:
        code = subprocess.call([executable, "--model=" + record["model"], "-c",
                                "model_reasoning_effort=" + json.dumps(record["effort"]), "--", prompt])
    except OSError as exc:
        print(f"Could not start Codex: {exc}", file=sys.stderr)
        code = 127
    with locked(path.parent):
        record.update(state="exited", exit_code=code)
        save(path, record)
    print(f"Worker exited with code {code}. Worktree retained.", flush=True)
    shell = os.environ.get("SHELL") or "/bin/sh"
    os.execl(shell, shell)


def main():
    os.umask(0o077)
    if len(sys.argv) == 4 and sys.argv[1] == "_worker":
        return worker(Path(sys.argv[2]), sys.argv[3])
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True)
    add_parser(commands)
    for name, handler in (("start", start), ("attach", attach_command), ("status", status)):
        commands.add_parser(name).set_defaults(func=handler)
    launch = commands.add_parser("dispatch")
    launch.add_argument("issue", metavar="TASK-N")
    launch.add_argument("--checkout", required=True)
    launch.add_argument("--revision", required=True, type=int)
    launch.add_argument("--model", required=True)
    launch.add_argument("--effort", required=True, choices=["low", "medium", "high", "xhigh", "max", "ultra"])
    launch.add_argument("--base")
    launch.set_defaults(func=dispatch)
    args = parser.parse_args()
    try:
        return args.func(args)
    except subprocess.CalledProcessError as exc:
        parser.exit(1, f"maestro: {(exc.stderr or '').strip() or 'subprocess failed'}\n")
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f"maestro: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
