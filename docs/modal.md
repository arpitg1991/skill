# Modal Manual Setup and Runs

This document covers manual-only orchestration in Modal. GitHub Actions are intentionally out of scope.

## Prerequisites
- Modal CLI installed and authenticated (`modal token new`)
- Secrets created in Modal:
  - `pinchbench-secrets` with `OPENROUTER_API_KEY` and `PINCHBENCH_TOKEN`
- Volume created in Modal:
  - `pinchbench-results`

## Files
- `modal_app.py` contains the Modal entry points.
- `Dockerfile.benchmark` defines the base image.
- `.github/benchmark-models.yml` defines the full model list.

## Manual Smoke Run
The smoke run uses GPT 5.4 and Opus 4.6 and skips leaderboard uploads.

```bash
modal run modal_app.py::orchestrate_smoke
```

## Full Manual Run
Runs the entire `.github/benchmark-models.yml` list. Uploads are enabled by default.

```bash
modal run modal_app.py::orchestrate_all
```

To disable uploads:

```bash
modal run modal_app.py::orchestrate_all --upload false
```

## Results and Logs
- Results are written to the Modal volume at `/results`.
- Logs are written to `/results/logs/{timestamp}_{model}.log`.
- Each run returns a payload with `exit_code`, `duration_seconds`, `results_path`, and a `log_tail`.
