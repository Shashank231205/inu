# inu-lab

Benchmarks and experiments for choosing INU's models. Development only, never deployed.

The heavy speech libraries are in the root `lab` dependency group, so CI and servers never install them:

```sh
uv sync --group lab
uv run inu bench llm
```
