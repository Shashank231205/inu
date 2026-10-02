# 0004. Layered configuration with SOPS-encrypted secrets

- **Status:** accepted
- **Date:** 2026-10-02

## Context

NFR-9 forbids environment-specific values in code. INU runs on at least two machines with different needs: the laptop, and a VM that may sometimes be offline. It needs API keys for free cloud providers.

Secrets must never reach git in plaintext (threat T9). They still need to be versioned, so that a VM can be rebuilt from the repo alone (NFR-6).

## Decision

**Configuration:**
- pydantic-settings, with layers from lowest to highest priority: `base.yaml`, then the profile YAML, then a secrets directory, then `.env`, then environment variables.
- The schema in code has **no defaults** for operational values. `base.yaml` is the single source of defaults.
- The schema forbids unknown keys, so typos fail at startup.
- The settings object is frozen, and validation errors never echo input values.

**Secrets:**
- SOPS with age keys. Encrypted dotenv files live in `secrets/` and are committed.
- `sops exec-env` decrypts into one process's environment only, so the application code never handles encryption.
- Values are `SecretStr`: redacted in `repr`, logs and dumps.

## Alternatives considered

| Option | Why not |
|---|---|
| Plaintext `.env` only | Secrets aren't versioned; one careless commit leaks them |
| HashiCorp Vault / Infisical (self-hosted) | Another always-on service to run, secure and back up, on a 12 GB VM |
| Hosted secret managers (Doppler, cloud KMS) | Free tiers change, and they put a third party on the startup path |
| OS keyring | Doesn't work for headless Linux on the VM, and isn't versioned |
| Defaults in code plus YAML overrides | Two places to look for every value; defaults drift from docs |

## Consequences

- Losing the age private key means losing the encrypted secrets. Backup steps are in [configuration.md](../configuration.md).
- Each new machine needs its own age key added as a recipient.
- SOPS and age are required tools on every machine that runs INU with secrets.
- CI runs with the `test` profile, which needs no secrets.
