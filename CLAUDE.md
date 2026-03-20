# Deltona Memory

See @README.md for an overview of this project, and view @AGENTS.md for the agents.

## Avoiding Permission Prompts

Bash commands containing `$()` subshells trigger interactive permission prompts. Avoid these:

- **Git commits**: write message to `/tmp/commit-msg` with `cat > /tmp/commit-msg <<'EOF'`, then
  `git commit -S -s -F /tmp/commit-msg`. Never use `-m "$(cat <<'EOF' ...)"`.
- **Command substitution**: prefer chaining with `&&` and temp files over `$()` inline.
- **Backticks**: same issue as `$()` — avoid `` `command` `` in Bash tool calls.
- **Pipes into commands** are fine (`echo foo | git commit --stdin` etc.).
