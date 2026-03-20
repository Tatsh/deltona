# Commit

Create high-quality Git commits for all pending changes.

## Gathering context

Run these in parallel:

1. `git diff` - unstaged changes.
2. `git diff --cached` - staged changes.
3. `git status` - untracked files and overall state.
4. `git log --no-merges --format='%s%n%b---' -20 | grep -v '^bump:' | grep -iv dependabot` -
   recent commit message style examples.

## Running agents

After gathering context but before committing, determine which agents to run based on the changed
files. Launch each agent sequentially using the Agent tool with subagent_type `general-purpose`,
telling it to follow the corresponding `.claude/agents/<name>.md` file. Scope each agent to only the
changed files, not the entire project.

### When Python code is being committed

If any changed files are under `deltona/` or `tests/`, run the following agents **in order**:

1. **python-moderniser** - upgrade to modern Python features.
1. **click-auditor** - validate Click command consistency. **Only run if files under
   `deltona/commands/` changed.**
1. **docstring-fixer** - fix missing or incomplete docstrings.
1. **copy-editor** - fix prose in comments, docstrings, and strings.
1. **test-writer** - generate/update tests for new/changed code. **Skip if the only changes are in
   `tests/`.**
1. **coverage-improver** - find coverage gaps and write tests.
1. **qa-fixer** - format and fix lint/spelling issues.

### Always run

- **changelog** - update `CHANGELOG.md` with entries for the changes. After it completes, check if
  `CHANGELOG.md` was modified (`git diff CHANGELOG.md`). If it was, it will be staged together with
  the relevant commit.

## Analysing changes

Group changed files by component. Determine if one commit or multiple logical commits are needed.

### Incidental files

The following files do not count when determining the component prefix, unless they are the **only**
file in a commit:

- `CHANGELOG.md`
- `.vscode/dictionary.txt`

For example, if a commit contains `deltona/commands/main.py`, `tests/test_main_command.py`, and
`CHANGELOG.md`, the component is determined by `deltona/commands/main.py` and
`tests/test_main_command.py` only. `CHANGELOG.md` is simply staged alongside them.

If `CHANGELOG.md` is the only file being committed, use the `changelog:` prefix. If
`.vscode/dictionary.txt` is the only file, use `dictionary:` prefix.

### When to split into multiple commits

- Changes span unrelated components (e.g. `deltona/media.py` and `.claude/agents/release.md`).
- A refactor and a bug fix in the same file should be separate commits.
- New tests for existing code should be separate from the code changes they test only if the code
  changes are themselves separate.
- Dictionary updates (`.vscode/dictionary.txt`) should be committed first with message
  `dictionary: update`.

### When a single commit is fine

- All changes serve the same purpose within a closely related set of files.
- A bug fix and its test.

## Commit message format

```text
component.name: short description

Optional longer description explaining the why, not the what. Wrap at 72
characters.

Signed-off-by: Author Name <email>
Closes: #123
```

### Subject line rules

- Format: `component.name: short description`.
- Lowercase after the colon (unless a proper noun).
- No period at the end.
- Maximum 72 characters.
- Use imperative mood: 'add', 'fix', 'update', 'remove', not 'added', 'fixes', 'updated'.

### Component prefix rules

- Python file `deltona/media.py` → `deltona/media:`.
- Multiple files under `deltona/commands/` → `deltona/commands:`.
- Single command file `deltona/commands/admin.py` → `deltona/commands/admin:`.
- Workflow file `.github/workflows/qa.yml` → `workflows/qa:`.
- Multiple workflows → `workflows/*:`.
- Agent files `.claude/agents/*.md` → `.claude:` or specific agent name.
- Instruction files across all 3 locations → `project:` (since they span Copilot/Cursor/Claude).
- Test files `tests/test_media.py` → `tests/test_media:` (or `tests:` for multiple).
- Dictionary `.vscode/dictionary.txt` → `dictionary:` (only when committed alone).
- Top-level config (`pyproject.toml`, `package.json`) → `project:`.
- If changes span many unrelated areas → `project:`.
- CHANGELOG.md → `changelog:` (only when committed alone).
- CONTRIBUTING.md → `contributing:`.

### Trailers

- `Signed-off-by:` - always included on every commit. Use the author name and email from
  `git config user.name` and `git config user.email`.
- `Closes: #N` - when a commit closes a GitHub issue.
- `Fixes: #N` - when a commit fixes a bug reported in an issue.
- `Reviewed-by:` - if applicable.
- `Co-authored-by:` - if applicable.

## Making commits

1. Stage files for each logical commit using `git add` with specific file paths.
2. If `CHANGELOG.md` was updated by the changelog agent, stage it with the relevant commit.
3. Write the commit message to `/tmp/commit-msg` using the **Write** tool (not Bash `cat`), then
   commit with `git commit -S -s -F /tmp/commit-msg`.

4. If a pre-commit hook fails, fix the issue, re-stage (use appropriate agent if there is one), and
   try to commit again.
5. After all commits, run `git status` to verify clean state.

## Rules

- Never use `--no-verify` or `--no-gpg-sign`.
- Never amend existing commits unless explicitly asked.
- Never push unless explicitly asked.
- Always use `-S` for GPG signing and `-s` for sign-off.
- If there are no changes, do nothing.
- Stage specific files, never use `git add -A` or `git add .`.
