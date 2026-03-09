import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import modal


APP_NAME = "pinchbench"
REPO_MOUNT_PATH = "/workspace"
RESULTS_PATH = "/results"
LOGS_PATH = f"{RESULTS_PATH}/logs"
DEFAULT_SUITE = "all"
DEFAULT_RUNS = 1
DEFAULT_TIMEOUT_SECONDS = 2 * 60 * 60
SMOKE_MODELS = [
    "openrouter/openai/gpt-5.4",
    "openrouter/anthropic/claude-opus-4.6",
]


app = modal.App(APP_NAME)
results_volume = modal.Volume.from_name("pinchbench-results")

benchmark_image = modal.Image.from_dockerfile("Dockerfile.benchmark").add_local_dir(
    ".",
    remote_path=REPO_MOUNT_PATH,
    ignore=[".git", ".venv", "__pycache__", ".pytest_cache"],
)


def _load_models_from_repo() -> List[str]:
    import yaml

    config_path = Path(REPO_MOUNT_PATH) / ".github" / "benchmark-models.yml"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return payload.get("models", [])


def _tail_text(path: Path, max_bytes: int = 8000) -> str:
    if not path.exists():
        return ""
    size = path.stat().st_size
    start = max(size - max_bytes, 0)
    with path.open("rb") as handle:
        handle.seek(start)
        data = handle.read().decode("utf-8", errors="replace")
    return data


def _extract_results_path(log_text: str) -> Optional[str]:
    marker = "Saved results to "
    for line in log_text.splitlines()[::-1]:
        if marker in line:
            return line.split(marker, 1)[1].strip()
    return None


def _run_benchmark_command(
    model: str,
    suite: str,
    runs: int,
    output_dir: str,
    per_model_timeout: int,
    upload: bool,
    log_path: Path,
) -> Dict[str, Any]:
    import select
    import subprocess

    cmd = [
        "./scripts/run.sh",
        "--model",
        model,
        "--suite",
        suite,
        "--runs",
        str(runs),
        "--output-dir",
        output_dir,
        "--verbose",
    ]
    if not upload:
        cmd.append("--no-upload")

    start_time = time.time()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("w", encoding="utf-8") as log_handle:
        log_handle.write(f"Command: {' '.join(cmd)}\n")
        log_handle.write(
            f"Start: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(start_time))} UTC\n"
        )
        log_handle.write(
            f"Preflight: run.sh exists={Path(REPO_MOUNT_PATH, 'scripts', 'run.sh').exists()}\n"
        )
        log_handle.write(
            f"Preflight: OPENROUTER_API_KEY set={'OPENROUTER_API_KEY' in os.environ}\n"
        )
        log_handle.write(f"Preflight: PINCHBENCH_TOKEN set={'PINCHBENCH_TOKEN' in os.environ}\n")
        log_handle.flush()
        results_volume.commit()
        try:
            version_result = subprocess.run(
                ["openclaw", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            log_handle.write(
                "Preflight: openclaw --version exit=%s stdout=%s stderr=%s\n"
                % (
                    version_result.returncode,
                    version_result.stdout.strip(),
                    version_result.stderr.strip(),
                )
            )
        except subprocess.TimeoutExpired:
            log_handle.write("Preflight: openclaw --version timed out\n")
        except FileNotFoundError:
            log_handle.write("Preflight: openclaw not found\n")
        log_handle.flush()
        results_volume.commit()

        try:
            list_result = subprocess.run(
                ["openclaw", "agents", "list"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            log_handle.write(
                "Preflight: openclaw agents list exit=%s stdout=%s stderr=%s\n"
                % (
                    list_result.returncode,
                    list_result.stdout.strip(),
                    list_result.stderr.strip(),
                )
            )
        except subprocess.TimeoutExpired:
            log_handle.write("Preflight: openclaw agents list timed out\n")
        except FileNotFoundError:
            log_handle.write("Preflight: openclaw not found for agents list\n")
        log_handle.flush()
        results_volume.commit()

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        process = subprocess.Popen(
            cmd,
            cwd=REPO_MOUNT_PATH,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        timed_out = False
        last_heartbeat = start_time
        assert process.stdout is not None

        while True:
            if process.poll() is not None:
                break

            now = time.time()
            if now - start_time > per_model_timeout:
                timed_out = True
                log_handle.write(
                    f"Timeout: benchmark subprocess exceeded {per_model_timeout}s and was killed\n"
                )
                log_handle.flush()
                process.kill()
                break

            ready, _, _ = select.select([process.stdout], [], [], 1)
            if ready:
                line = process.stdout.readline()
                if line:
                    log_handle.write(line)
                    log_handle.flush()
                    results_volume.commit()
                    print(f"[{model}] {line}", end="")
            elif now - last_heartbeat >= 30:
                heartbeat = (
                    f"Heartbeat: benchmark still running at "
                    f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(now))} UTC\n"
                )
                log_handle.write(heartbeat)
                log_handle.flush()
                results_volume.commit()
                print(f"[{model}] {heartbeat}", end="")
                last_heartbeat = now

        # Drain any remaining output after process exits.
        for line in process.stdout:
            log_handle.write(line)
            log_handle.flush()
            results_volume.commit()
            print(f"[{model}] {line}", end="")

        process.wait()
        results_volume.commit()

    duration = time.time() - start_time
    log_tail = _tail_text(log_path)
    results_path = _extract_results_path(log_tail)

    return {
        "model": model,
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "duration_seconds": round(duration, 2),
        "log_path": str(log_path),
        "log_tail": log_tail,
        "results_path": results_path,
    }


@app.function(
    image=benchmark_image,
    cpu=16,
    memory=32768,
    timeout=DEFAULT_TIMEOUT_SECONDS,
    secrets=[modal.Secret.from_name("pinchbench-secrets")],
    volumes={RESULTS_PATH: results_volume},
)
def run_model_benchmark(
    model: str,
    suite: str = DEFAULT_SUITE,
    runs: int = DEFAULT_RUNS,
    per_model_timeout: int = DEFAULT_TIMEOUT_SECONDS,
    upload: bool = True,
) -> Dict[str, Any]:
    log_filename = model.replace("/", "_").replace(":", "_")
    log_path = Path(LOGS_PATH) / f"{int(time.time())}_{log_filename}.log"

    return _run_benchmark_command(
        model=model,
        suite=suite,
        runs=runs,
        output_dir=RESULTS_PATH,
        per_model_timeout=per_model_timeout,
        upload=upload,
        log_path=log_path,
    )


def _run_models(models: List[str], suite: str, upload: bool) -> List[Dict[str, Any]]:
    return list(
        run_model_benchmark.map(
            models,
            kwargs={
                "suite": suite,
                "runs": DEFAULT_RUNS,
                "per_model_timeout": DEFAULT_TIMEOUT_SECONDS,
                "upload": upload,
            },
        )
    )


@app.local_entrypoint()
def orchestrate_smoke(suite: str = DEFAULT_SUITE) -> None:
    results = _run_models(SMOKE_MODELS, suite=suite, upload=False)
    print(json.dumps(results, indent=2))


@app.local_entrypoint()
def orchestrate_all(suite: str = DEFAULT_SUITE, upload: bool = True) -> None:
    models = _load_models_from_repo()
    results = _run_models(models, suite=suite, upload=upload)
    print(json.dumps(results, indent=2))
