# Modal Manual Orchestration Plan

Scope: Manual-only runs in Modal. No GitHub Actions integration.

## Goals
- Validate the Modal execution path end-to-end before automation.
- Ensure observability and reliable results storage.
- Confirm the smoke run set: GPT 5.4 and Opus 4.6.

## Plan
1. Locate the Modal entry point and verify the manual run command (e.g., `modal run modal_app.py::orchestrate`).
2. Verify Modal prerequisites:
   - Secret `pinchbench-secrets` contains `OPENROUTER_API_KEY` and `PINCHBENCH_TOKEN`.
   - Volume `pinchbench-results` exists and is writable at `/results`.
   - `.github/benchmark-models.yml` is included in the image build context or otherwise accessible at runtime.
3. Add minimal observability for manual runs:
   - Stream logs to `/results/logs/{model}.log`.
   - Include `stderr`, `exit_code`, `duration`, and `results_path` in the return payload.
   - Add a per-model timeout guard inside `run_model_benchmark`.
4. Smoke run:
   - Limit to GPT 5.4 and Opus 4.6.
   - Confirm logs and results are written to the volume.
   - Verify any notifications or summary reporting (if enabled).
5. Expand to full model list and validate aggregation quality.
6. Document the manual run procedure and expected outputs in the repo.

## Smoke Run Model Set
- GPT 5.4
- Opus 4.6
