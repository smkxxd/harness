# ForgeTrace Review Pack

## Project pitch

ForgeTrace is a repository-aware local coding agent for repository-grounded engineering tasks. It wraps a model with code-aware retrieval, workspace context, explicit tools, state tracking, memory, run artifacts, and benchmark evidence.

## Architecture map

- `pico.cli` wires configuration, provider clients, workspace context, and the runtime.
- `forgetrace.ForgeTrace` is the public runtime API; the internal `pico` package remains as a compatibility layer.
- `pico.context_manager` builds bounded model context from prefix, memory, history, and the current request.
- `pico.tools` defines the explicit tool allowlist used by the runtime.
- `pico.run_store` writes per-run artifacts for review and replay.

## Benchmark evidence

Benchmark runs should preserve reproducibility metadata, task rows, summary counts, and failure categories so reviewers can distinguish runtime regressions from task or provider failures.

## Sample run artifact list

- `.pico/runs/<run_id>/task_state.json`
- `.pico/runs/<run_id>/trace.jsonl`
- `.pico/runs/<run_id>/report.json`
