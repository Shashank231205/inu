# CI/CD

GitHub Actions, defined in [`.github/workflows/`](../.github/workflows/).

## Workflows

| Workflow | Trigger | Jobs |
|---|---|---|
| `ci` | push to `main`, pull requests, called by `release` | `hooks`, `test` (Ubuntu + Windows), `test-arm` (public repos only), `gitleaks`, `audit` |
| `release` | tag `vX.Y.Z` | runs all of `ci`, checks that the tag matches the package version, builds wheels and sdists, publishes a GitHub release |

| Job | What it checks | Run it locally with |
|---|---|---|
| `hooks` | Every pre-commit hook except mypy: format, lint, secret guards, workflow lint | `uv run pre-commit run --all-files` |
| `test` | mypy strict + pytest with the 85% coverage gate, on the laptop's OS and on Linux | `uv run poe typecheck` · `uv run poe test` |
| `test-arm` | Tests on Linux ARM, the always-on VM's architecture | Not available locally |
| `gitleaks` | Secret scan of the whole git history | Not available locally (Windows blocks the binary, see ADR 0003) |
| `audit` | Known vulnerabilities in every locked dependency (pip-audit) | See below |

## Supply-chain rules

- **Pinned actions:** third-party actions are pinned to a full commit SHA, with the release tag in a comment. Dependabot updates both.
- **Cooldown:** Dependabot waits **7 days** before proposing a new release, so compromised releases are usually yanked before they reach INU.
- **Locked installs:** every job installs with `uv sync --locked`, so a lockfile that's out of date fails CI instead of being re-resolved silently.
- **Least privilege:** workflows get read-only tokens. Only the release job can write, and only to create the release.
- **No stored credentials:** checkouts use `persist-credentials: false`, so later steps can't reuse the token.
- **Workflow linting:** actionlint and zizmor run on every commit that touches `.github/`.

## Local dependency audit

```sh
uv export --locked --no-emit-workspace --format requirements-txt -o requirements.txt
uvx pip-audit --strict --disable-pip -r requirements.txt
```

On a network that intercepts HTTPS, pip-audit fails certificate checks. Point `REQUESTS_CA_BUNDLE` at a PEM export of the Windows root store for that one command.

## After the first push

These are repository settings, so they can't live in files:

1. **Settings → Branches → add a rule for `main`:**
   - require a pull request before merging
   - require these status checks (exact job names): `hooks (lint, format, secret guards)`, `test (ubuntu-latest)`, `test (windows-latest)`, `secret scan (full history)`, `dependency audit`, plus `test (linux arm64)` if the repo is public
   - block force pushes
2. **Settings → Code security:** enable Dependabot alerts and secret scanning push protection.

## Cutting a release

1. Bump `version` in `packages/core/pyproject.toml`.
2. Commit, then tag and push:

   ```sh
   git tag v0.2.0
   git push origin v0.2.0
   ```

If the tag doesn't match the version, the release job fails before building anything.
