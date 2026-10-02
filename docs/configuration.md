# Configuration

Every INU process builds one immutable, validated `Settings` object at startup. If anything is missing, misspelled or invalid, the process stops with a message that names the exact key. It never falls back to a guess.

## Layers

Highest priority first:

| # | Source | Example | Use it for |
|---|---|---|---|
| 1 | `INU_*` environment variables | `INU_LOG__LEVEL=DEBUG` | One-off overrides, and secrets injected by SOPS |
| 2 | `.env` in the working directory | copy of `.env.example` | Personal local overrides (git-ignored) |
| 3 | Secrets directory (`INU_SECRETS_DIR`) | `/run/secrets/inu_instance_name` | Container secrets, one file per key |
| 4 | `config/profiles/<profile>.yaml` | `laptop.yaml` | What differs per machine |
| 5 | `config/base.yaml` | | **All defaults.** The schema in code has none, so this is the one place to look. |

Nested keys are joined with `__` in environment variables: `log.level` becomes `INU_LOG__LEVEL`.

Bootstrap variables, read before anything else:

| Variable | Meaning | Default |
|---|---|---|
| `INU_PROFILE` | Profile to load (`laptop`, `vm`, `test`) | none; required |
| `INU_CONFIG_DIR` | Directory holding `base.yaml` and `profiles/` | `./config` |
| `INU_SECRETS_DIR` | Directory of per-key secret files | not used |

## Commands

```sh
uv run inu config check --profile laptop   # validate only
uv run poe config laptop                    # effective config, secrets loaded and redacted
```

## Secrets

Secrets live in `secrets/<profile>.enc.env`, encrypted with [SOPS](https://github.com/getsops/sops) and [age](https://github.com/FiloSottile/age). Only the values are encrypted, so key names stay readable in diffs. The plaintext only ever exists inside the environment of the process that needs it.

```sh
uv run poe secrets-edit laptop    # opens the decrypted file in your editor, re-encrypts on save
```

At runtime, `sops exec-env secrets/laptop.enc.env "<command>"` decrypts into that command's environment, where layer 1 picks the values up.

Leave a key blank until you have it; blank means "not set". Turning on `features.cloud_llm` without any provider key is a startup error.

### The age key

The private key is at `%APPDATA%\sops\age\keys.txt` on Windows (`~/.config/sops/age/keys.txt` on Linux). Its file permissions allow only your account to read it.

**Back it up somewhere offline, such as a password manager.** If you lose it, the encrypted secrets can't be recovered. You would have to create new API keys and encrypt them again.

To let another machine (for example the VM) decrypt:

1. Generate a key there: `age-keygen -o ~/.config/sops/age/keys.txt`.
2. Add its public key to `.sops.yaml`.
3. Run `sops updatekeys secrets/<profile>.enc.env`.

## Adding a setting

1. Add the field to the right model in `packages/core/src/inu/config/settings.py`, with no default unless it's a secret.
2. Add the default to `config/base.yaml`, and per-profile overrides where values differ.
3. Add a test if the field has validation rules.

The shipped profiles are loaded in CI, so a field missing from `base.yaml` fails the build, not production.
