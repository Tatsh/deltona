# Agents and Instruction Files

## Agents (Claude Code)

| Agent                                              | Purpose                                      |
| -------------------------------------------------- | -------------------------------------------- |
| [markdownlint-fixer](agents/markdownlint-fixer.md) | Fix markdownlint-cli2 issues.                |
| [mypy-fixer](agents/mypy-fixer.md)                 | Fix mypy errors and eliminate `Any`.         |
| [python-expert](agents/python-expert.md)           | General expert-level Python coding.          |
| [python-moderniser](agents/python-moderniser.md)   | Upgrade code to modern Python features.      |
| [qa-fixer](agents/qa-fixer.md)                     | Run `yarn format` and `yarn qa` until clean. |
| [release](agents/release.md)                       | Changelog, version bump, push.               |

## Instruction Files

Rules are maintained in parallel across three tool locations. When adding or modifying rules, update
all three.

### Copilot (`.github/instructions/`)

| File                                                              | Scope                                 |
| ----------------------------------------------------------------- | ------------------------------------- |
| [general](.github/instructions/general.instructions.md)           | Project-wide conventions              |
| [python](.github/instructions/python.instructions.md)             | Python coding (`**/*.py`, `**/*.pyi`) |
| [python-tests](.github/instructions/python-tests.instructions.md) | Test conventions (`tests/**/*.py`)    |
| [json-yaml](.github/instructions/json-yaml.instructions.md)       | JSON and YAML files                   |
| [toml-ini](.github/instructions/toml-ini.instructions.md)         | TOML and INI files                    |
| [markdown](.github/instructions/markdown.instructions.md)         | Markdown files                        |

### Cursor (`.cursor/rules/`)

| File                                           | Scope                                 |
| ---------------------------------------------- | ------------------------------------- |
| [python](.cursor/rules/python.mdc)             | Python coding (`**/*.py`, `**/*.pyi`) |
| [python-tests](.cursor/rules/python-tests.mdc) | Test conventions (`tests/**/*.py`)    |
| [json-yaml](.cursor/rules/json-yaml.mdc)       | JSON and YAML files                   |
| [toml-ini](.cursor/rules/toml-ini.mdc)         | TOML and INI files                    |
| [markdown](.cursor/rules/markdown.mdc)         | Markdown files                        |
| [mypy-fixer](.cursor/rules/mypy-fixer.mdc)     | Mypy fixer guidelines                 |
