# INU

A personal AI system you talk to. Say its name and it answers fast enough to feel like a conversation. It remembers you, works through tools and agents, shows ideas visually, and improves every week by finetuning on its own conversations.

Local first, free to run, built like production software.

> **Status:** Phase 4 of 77, Foundations. See the [roadmap](docs/roadmap.md).

## Architecture

| Tier | Runs on | Responsibility |
|---|---|---|
| Reflex | Laptop | Wake word, voice activity detection, speech-to-text, text-to-speech, fast local model |
| Big brain | Free inference APIs behind one interface | Hard reasoning, long answers, vision. Off in private mode. |
| Spine | Always-on ARM VM | Memory (Postgres + pgvector), API, scheduler, nightly learning |
| Gym | Free cloud GPUs | Finetuning, evals, simulations |

The reasoning is in [ADR 0002](docs/adr/0002-hybrid-compute-topology.md).

## Docs

- [Vision](docs/vision.md): what INU is, its principles and non-goals
- [Requirements](docs/requirements.md): functional and non-functional, with measurable targets
- [Threat model](docs/threat-model.md): STRIDE per component
- [Roadmap](docs/roadmap.md): 77 phases in 14 stages
- [Configuration](docs/configuration.md): layers, profiles and encrypted secrets
- [Observability](docs/observability.md): turns, stages, logs, traces, metrics, error taxonomy
- [CI/CD](docs/ci.md): workflows, supply-chain rules, releases
- [Architecture decisions](docs/adr/)

## Development

Requires [uv](https://docs.astral.sh/uv/), which installs the right Python version on its own. Loading secrets also requires [SOPS](https://github.com/getsops/sops) and [age](https://github.com/FiloSottile/age).

```sh
uv sync                 # create the environment
uv run poe hooks        # install git hooks
uv run poe check        # lint, type check, test (same as CI)
```

`uv run poe` lists every task.

Commits follow [Conventional Commits](https://www.conventionalcommits.org/). A commit-msg hook enforces it.

## Layout

```
packages/core/   core library: domain types, interfaces, orchestration
config/          base.yaml (all defaults) and per-machine profiles
secrets/         SOPS-encrypted secrets, one file per profile
docs/            vision, requirements, threat model, roadmap, ADRs
```

Deployables (`apps/voice`, `apps/api`, `apps/worker`) and training code (`training/`, `evals/`) are added in the phases that introduce them.

## License

[MIT](LICENSE)
