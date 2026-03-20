# Deltona Memory

See @README.md for an overview of this project, and view @AGENTS.md for the agents.

## Avoiding Permission Prompts

Bash commands containing `$()` subshells trigger interactive permission prompts. Avoid these:

- **Git commits**: use the **Write** tool to write the message to `/tmp/commit-msg`, then run
  `git commit -S -s -F /tmp/commit-msg` via Bash. Never use `-m "$(cat <<'EOF' ...)"` or
  `cat > /tmp/commit-msg` in Bash (both trigger permission prompts).
- **Command substitution**: prefer chaining with `&&` and temp files over `$()` inline.
- **Backticks**: same issue as `$()` — avoid `` `command` `` in Bash tool calls.
- **Pipes into commands** are fine (`echo foo | git commit --stdin` etc.).
