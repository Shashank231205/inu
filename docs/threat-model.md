# Threat model

Method: STRIDE per component. Review this file whenever a component or trust boundary changes.

## Assets

1. **Personal data:** conversations, memories, calendar, email, files.
2. **Control of the laptop:** tools can open apps, run code and change files.
3. **Credentials:** API keys and OAuth tokens.
4. **Model integrity:** finetuned weights and the training data behind them.

## Trust boundaries

```
[Microphone / user]──(1)──►[Laptop: voice + reflex model]──(2)──►[Cloud LLM providers]
                                     │
                                    (3) Tailscale
                                     ▼
                           [VM: API, DB, workers]──(4)──►[MCP servers / web / integrations]
                                     │
                                    (5)
                                     ▼
                           [Training GPUs + model hub]
```

## Threats and mitigations

| # | Component | STRIDE | Threat | Mitigation | Phase |
|---|---|---|---|---|---|
| T1 | Voice input | Spoofing | Someone else, or a TV/recording, gives commands | Speaker verification; confirmation for sensitive actions; replay-detection heuristics | 40, 54 |
| T2 | Voice input | Elevation | Overheard speech triggers a destructive tool | Permission tiers; destructive actions need explicit confirmation | 23 |
| T3 | LLM / tools | Tampering | Prompt injection in web pages, emails or tool output takes over the agent | Tool output treated as data, never instructions; per-tool allowlists; a human gate for outward-facing actions; red-team suite | 23, 61 |
| T4 | MCP servers | Tampering | A malicious or compromised server poisons tool descriptions | Gateway allowlist; pinned server versions; tool descriptions reviewed on change; process sandbox | 58, 61 |
| T5 | Cloud providers | Info disclosure | Personal data sent to a third party | PII scrubbing; private mode; data classification on memories | 14 |
| T6 | API | Spoofing | Unauthenticated access to INU | No public endpoints (Tailscale only); API keys + JWT; per-device identity | 28, 30 |
| T7 | API | Denial of service | A runaway client or agent exhausts resources or quotas | Token-bucket rate limits; per-task budgets; circuit breakers | 13, 28, 54 |
| T8 | Database | Tampering / loss | Corruption, accidental delete, VM loss | Least-privilege DB roles; append-only event log; encrypted off-site backups; restore drills | 17, 30 |
| T9 | Secrets | Info disclosure | Keys leaked through git or logs | SOPS + age encryption; detect-secrets pre-commit hook, gitleaks in CI; log redaction | 1, 2, 3 |
| T10 | Code sandbox | Elevation | Generated code escapes and touches the host | Docker with no host mounts, no network by default, CPU and memory limits, non-root user | 67 |
| T11 | Training pipeline | Tampering | Bad or poisoned samples degrade the model | Review queue; data filters; eval gate; shadow mode; one-command rollback | 34, 42 |
| T12 | Dependencies | Tampering | Supply-chain compromise | Lockfile with hashes; dependency scanning; minimal dependencies | 1, 4 |
| T13 | Audit | Repudiation | Unclear who or what performed an action | Every tool call and agent step recorded as an immutable event with its trigger | 21, 72 |

## Accepted risks

- A cloud provider can see the requests it handles. That is acceptable for non-private requests after PII scrubbing, and private mode exists for everything else.
- A single laptop and a single VM are single points of failure. The reflex layer works offline, and the VM can be rebuilt from backups within the NFR-6 target.
