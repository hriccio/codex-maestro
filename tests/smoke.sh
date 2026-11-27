#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d)"
export HOME="$scratch/home" TMUX_TMPDIR="$scratch/socket"
unset TMUX
mkdir -p "$HOME/.agents/skills" "$TMUX_TMPDIR" "$scratch/bin"
cp -R "$root/skills/codex-maestro" "$HOME/.agents/skills/"
trap 'tmux kill-server 2>/dev/null || true; rm -rf "$scratch"' EXIT
export PATH="$scratch/bin:$PATH" GIT_CONFIG_NOSYSTEM=1
cat > "$scratch/bin/codex" <<'STUB'
#!/bin/sh
for arg do prompt="$arg"; done
printf '%s' "$prompt" > worker-prompt
STUB
chmod +x "$scratch/bin/codex"
maestro() { python3 -B "$HOME/.agents/skills/codex-maestro/scripts/maestro.py" "$@"; }
git init -q "$scratch/repo"
cd "$scratch/repo"
printf 'committed\n' > tracked
git add tracked
git -c user.name=Tester -c user.email=test@example.com commit -qm baseline
git remote add origin git@github.com:example/project.git
printf 'dirty\n' > tracked
printf '%s\n' '$(touch BAD)' > "$scratch/scope"
maestro task create --repository example/project --title Smoke --body-file "$scratch/scope" >/dev/null
maestro task transition TASK-1 ready --revision 1 >/dev/null
maestro start >/dev/null
dispatch() { maestro dispatch TASK-1 --checkout "$PWD" --revision "$1" --model stub --effort medium --base HEAD; }
if dispatch 1; then exit 1; fi
git remote set-url origin https://github.com/example/wrong.git
if dispatch 2; then exit 1; fi
git remote set-url origin git@github.com:example/project.git
(
    set +e
    dispatch 2 > "$scratch/first" 2>&1
    echo "$?" > "$scratch/first-code"
) &
first_pid=$!
(
    set +e
    dispatch 2 > "$scratch/second" 2>&1
    echo "$?" > "$scratch/second-code"
) &
second_pid=$!
wait "$first_pid" "$second_pid"
test "$(( $(cat "$scratch/first-code") + $(cat "$scratch/second-code") ))" -eq 1
if test "$(cat "$scratch/first-code")" -eq 0; then
    worktree="$(tail -n 1 "$scratch/first")"
else
    worktree="$(tail -n 1 "$scratch/second")"
fi
for ((i=0; i<100; i++)); do
    if maestro status | grep -q '"state": "exited"'; then break; fi
    sleep .05
done
maestro status | grep -q '"exit_code": 0'
test "$(cat tracked)" = dirty
test "$(cat "$worktree/tracked")" = committed
test ! -e "$worktree/BAD"
grep -Fq '$(touch BAD)' "$worktree/worker-prompt"
if dispatch 2; then exit 1; fi
maestro task create --repository example/project --title Consumer >/dev/null
maestro task block TASK-2 --by TASK-1 --revision 1 >/dev/null
maestro task transition TASK-2 ready --revision 2 >/dev/null
if maestro dispatch TASK-2 --checkout "$PWD" --revision 3 --model stub --effort medium --base HEAD; then
    exit 1
fi
maestro task create --repository example/project --title "Failed launch" >/dev/null
maestro task transition TASK-3 ready --revision 1 >/dev/null
printf '#!/bin/sh\nexit 1\n' > .git/hooks/post-checkout
chmod +x .git/hooks/post-checkout
if maestro dispatch TASK-3 --checkout "$PWD" --revision 2 --model stub --effort medium --base HEAD; then
    exit 1
fi
maestro status | grep -q '"state": "failed"'
maestro task show TASK-3 | grep -q '"state": "in_progress"'
tmux kill-server
maestro task backup "$scratch/queue.sqlite3" >/dev/null
rm "$HOME/.local/share/codex-maestro/tasks.sqlite3"
maestro task restore "$scratch/queue.sqlite3" >/dev/null
maestro task show TASK-1 | grep -q '"state": "in_progress"'
