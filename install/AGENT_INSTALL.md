# Install Arthur's skills

This file is written for an AI agent. Follow it literally.

Install two skills:

| SKILL.md name | Repository | Purpose |
|---|---|---|
| `instron-tensile-analysis` | https://github.com/ArthurEccleston/instron-tensile-analysis-skill | Instron foil tensile data: tensile strength and elongation at break |
| `grain-size` | https://github.com/ArthurEccleston/grain-size-analyzer | SEM orientation-contrast grain-size statistics |

Both repositories have `SKILL.md` at their root: the repository **is** the skill.

## Option A — run the installer

Linux / macOS / Git Bash:

```sh
curl -fsSL https://raw.githubusercontent.com/ArthurEccleston/grain-size-analyzer/main/install/install-skills.sh \
  | sh -s -- "$HOME/.claude/skills"
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/ArthurEccleston/grain-size-analyzer/main/install/install-skills.ps1 | iex
```

Pass a different destination when your agent uses another skills directory:

```sh
sh install-skills.sh /path/to/skills
```

## Option B — install manually

For each row in the table:

```sh
git clone --depth 1 <repository>.git <skills-dir>/<SKILL.md name>
rm -rf <skills-dir>/<SKILL.md name>/.git
```

Then verify:

```sh
test -f <skills-dir>/instron-tensile-analysis/SKILL.md
test -f <skills-dir>/grain-size/SKILL.md
```

If `git` is unavailable, download the repository zip/tarball for the `main`
branch and extract it so that `SKILL.md` is directly inside the target
directory.

## Dependencies

- `grain-size`: Python 3.10–3.13.

  ```sh
  python -m pip install -r <skills-dir>/grain-size/requirements.txt
  ```

- `instron-tensile-analysis`: Python with `openpyxl`.

  ```sh
  python -m pip install openpyxl
  ```

Prefer a virtual environment when one is available. Do not install into a
system Python when the environment is externally managed.

## Finish

1. Read `<skills-dir>/grain-size/SKILL.md` and
   `<skills-dir>/instron-tensile-analysis/SKILL.md`.
2. Confirm to the user which directory the skills were installed into and
   whether dependencies were installed.
3. If `github.com` is blocked, configure the network proxy first and retry.
   Do not silently skip a repository.
