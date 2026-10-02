# INU: Vision

## What INU is

INU is a personal AI system that you talk to by voice. Say its name and it answers fast enough to feel like a conversation, not a request. It remembers you, does real work through tools and agents, shows ideas visually when words aren't enough, and gets better every week.

It runs on hardware you own, with free cloud services added only where they help. The design never depends on any one of them.

## Principles

1. **Latency is a feature.** The voice loop is engineered against a budget, and every stage is measured. A slow but clever answer is worse than a quick, honest "give me a moment".
2. **Local first, cloud when it helps.** The real-time path (wake word, speech, the fast model) works offline. Cloud models are interchangeable providers behind one interface, never dependencies.
3. **Nothing is free forever.** Free tiers change, so every external service sits behind an adapter and its limits live in config.
4. **Learning is gated.** INU updates its memory every day and its weights every week. A new model ships only if it beats the current one on a fixed eval suite.
5. **The user stays in control.** Destructive or outward-facing actions need approval. Private mode keeps everything on the machine. Every action is logged and, where possible, reversible.
6. **Honest output.** INU separates what it knows, what it calculated and what it is guessing, and says which is which.
7. **Built like production software.** Typed, tested, observed, documented. Every real decision gets an ADR.

## Non-goals

- Serving anyone other than its owner. INU is a single-user system, and multi-tenant scale is out of scope.
- Imitating a real person's voice or identity.
- Being the biggest model. INU wins on latency, memory and fit to its owner, not on parameter count.
- Infrastructure for its own sake (Kubernetes, Kafka, microservices) when simpler tools meet the requirements.

## How we know it is working

| Signal | Target |
|---|---|
| Time from end of speech to INU's first audio (p95) | < 900 ms |
| Correct wake detections | > 95% |
| False wakes | < 1 per 10 hours |
| Facts INU remembers correctly a week later | > 90% on the memory eval suite |
| Weekly model releases that pass the gate | Every release scores at least as high as the one before |
| Uptime of always-on services | 99% monthly |
| Monthly running cost | ₹0 |

See [requirements.md](requirements.md) for the full list and [roadmap.md](roadmap.md) for the build order.
