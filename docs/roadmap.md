# Roadmap

77 phases in 14 stages. Every phase ends with code that runs, tests, and numbers wherever performance matters. Status: ⬜ not started · 🟨 in progress · ✅ done.

## Dependency order

```
A Foundations → B Voice → C Brain → D Memory + event log ─┬─► E Tools → K MCP → J Agents → M Simulation lab
                                                           ├─► F Platform → H Iron Man layer → L Visual engine
                                                           └─► N Time machine (builds on the event log from D)
G Model training runs in parallel from Phase 33, once real conversation data exists.
I Hardening runs last and repeats before every major release.
```

The immutable event log is built in Stage D, not Stage N. That way every event since the first release can be replayed.

## A: Foundations
| # | Phase | Status |
|---|---|---|
| 0 | Vision, requirements, threat model | ✅ |
| 1 | Monorepo and toolchain | ✅ |
| 2 | Config and secrets | ✅ |
| 3 | Observability base: (a) in-process logs, traces, metrics ✅ · (b) collector + Grafana stack, needs Docker | 🟨 |
| 4 | CI/CD: workflows written and linted ✅ · first run on GitHub, needs the push | 🟨 |

## B: Real-time voice
| # | Phase | Status |
|---|---|---|
| 5 | Audio I/O engine | ⬜ |
| 6 | Model bake-off on target hardware | ⬜ |
| 7 | Streaming STT + VAD | ⬜ |
| 8 | Streaming TTS | ⬜ |
| 9 | Voice pipeline + state machine | ⬜ |
| 10 | Barge-in and cancellation | ⬜ |
| 11 | Latency engineering | ⬜ |

## C: Brain
| # | Phase | Status |
|---|---|---|
| 12 | LLM provider layer | ⬜ |
| 13 | Resilience: fallback chain, circuit breakers, quota tracking | ⬜ |
| 14 | Router v1, private mode, PII scrubbing | ⬜ |
| 15 | Persona and prompt system | ⬜ |
| 16 | Dialog and context manager | ⬜ |

## D: Memory and data platform
| # | Phase | Status |
|---|---|---|
| 17 | Schema design and migrations, including the event log | ⬜ |
| 18 | Repositories and transactions | ⬜ |
| 19 | Vector memory with hybrid search | ⬜ |
| 20 | Memory lifecycle | ⬜ |
| 21 | Postgres job queue | ⬜ |
| 22 | Nightly consolidation | ⬜ |

## E: Tools
| # | Phase | Status |
|---|---|---|
| 23 | Tool framework and permission tiers | ⬜ |
| 24 | Core skills | ⬜ |
| 25 | Integrations (OAuth) | ⬜ |
| 26 | Multi-step agent loop | ⬜ |

## F: Platform and deployment
| # | Phase | Status |
|---|---|---|
| 27 | REST + WebSocket API | ⬜ |
| 28 | Auth and rate limiting | ⬜ |
| 29 | Caching layer | ⬜ |
| 30 | Always-on deployment, backups, restore drills | ⬜ |
| 31 | Clients: Telegram, phone PWA, tray app | ⬜ |
| 32 | SLOs, alerting, load tests | ⬜ |

## G: Model training
| # | Phase | Status |
|---|---|---|
| 33 | Eval harness (built first) | ⬜ |
| 34 | Data engine | ⬜ |
| 35 | Distillation + SFT | ⬜ |
| 36 | Preference tuning (DPO / ORPO / KTO) | ⬜ |
| 37 | Continual learning and adapter merging | ⬜ |
| 38 | Quantization and serving study | ⬜ |
| 39 | STT finetune for the owner's voice | ⬜ |
| 40 | Wake word and speaker verification training | ⬜ |
| 41 | Learned router | ⬜ |
| 42 | MLOps automation: shadow, canary, rollback | ⬜ |
| 43 | Voice finetune (optional, consented voice only) | ⬜ |

## H: Iron Man layer
| # | Phase | Status |
|---|---|---|
| 44 | HUD dashboard | ⬜ |
| 45 | Proactive INU | ⬜ |
| 46 | Vision: screen and presence | ⬜ |
| 47 | Multi-device presence | ⬜ |
| 48 | Tone awareness | ⬜ |

## I: Hardening
| # | Phase | Status |
|---|---|---|
| 49 | Security audit and red-team suite | ⬜ |
| 50 | Performance pass | ⬜ |
| 51 | Docs and showcase | ⬜ |

## J: Multi-agent system
| # | Phase | Status |
|---|---|---|
| 52 | Agent runtime: supervisor, workers, blackboard | ⬜ |
| 53 | Durable execution | ⬜ |
| 54 | Human-in-the-loop approvals and budgets | ⬜ |
| 55 | Agent observability and replay | ⬜ |
| 56 | Agent evals | ⬜ |

Work agents (each a plugin with its own evals): coder, researcher, data analyst, job hunter, inbox/calendar, meeting, browser, ops.

## K: MCP
| # | Phase | Status |
|---|---|---|
| 57 | INU as an MCP client | ⬜ |
| 58 | MCP gateway with policy | ⬜ |
| 59 | Tool retrieval at scale | ⬜ |
| 60 | INU as an MCP server | ⬜ |
| 61 | MCP security and red-team | ⬜ |

## L: Visual engine
| # | Phase | Status |
|---|---|---|
| 62 | Generative UI protocol (typed scene specs) | ⬜ |
| 63 | Renderers: charts, diagrams, 3D, maps, math, graphs | ⬜ |
| 64 | Conversational, stateful visuals | ⬜ |
| 65 | Gesture control | ⬜ |
| 66 | AR mode | ⬜ |

## M: Simulation lab
| # | Phase | Status |
|---|---|---|
| 67 | Sandboxed compute | ⬜ |
| 68 | Model-building agent | ⬜ |
| 69 | Simulation types | ⬜ |
| 70 | Parameter exploration | ⬜ |
| 71 | End-to-end demo | ⬜ |

## N: Time machine
| # | Phase | Status |
|---|---|---|
| 72 | Event-sourced state rebuild (CQRS read models) | ⬜ |
| 73 | Bitemporal memory | ⬜ |
| 74 | Replay, fork and compare | ⬜ |
| 75 | Personal timeline | ⬜ |
| 76 | Snapshots and undo | ⬜ |
