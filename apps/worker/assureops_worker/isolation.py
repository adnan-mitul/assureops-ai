"""Disposable execution of one test step outside the worker process.

`subprocess` mode: `python -I` with a scrubbed environment (no database,
broker, storage or platform keys), killed at the deadline.
`container` mode: a fresh container per step with no capabilities, read-only
filesystem, memory/CPU/PID limits and a runner-only network.
The capsule (including target credentials for this one step) travels on stdin
only; nothing is written to disk.
"""

import json
import os
import subprocess
import sys

from assureops_domain.config import settings

SAFE_ENV_KEYS = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL")
MAX_OUTPUT = 4_000_000


class RunnerFailure(Exception):
    pass


def scrubbed_env() -> dict:
    env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", NO_PROXY="*")
    return env


def command() -> list[str]:
    cfg = settings()
    if cfg.runner_mode == "container":
        return ["docker", "run", "--rm", "-i", "--network", "assureops-runner", "--memory", "256m", "--cpus", "0.5",
                "--pids-limit", "64", "--read-only", "--tmpfs", "/tmp:rw,size=16m", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--user", "65534:65534", cfg.runner_image]
    return [sys.executable, "-I", "-m", "assureops_connectors.sandbox"]


def run_capsule(capsule: dict, *, timeout: float, on_tick=None) -> dict:
    """Run one capsule; `on_tick` is called about every 10 s (lease renewal) and may raise to abort."""
    proc = subprocess.Popen(command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env=scrubbed_env(), cwd=os.path.dirname(sys.executable))
    data = json.dumps(capsule).encode()
    elapsed, slice_, pending_input = 0.0, 10.0, data
    try:
        while True:
            try:
                # communicate() keeps reading stdout while waiting, so a large result cannot deadlock the pipe.
                out, _ = proc.communicate(input=pending_input, timeout=min(slice_, max(timeout - elapsed, 0.1)))
                break
            except subprocess.TimeoutExpired:
                pending_input = None
                elapsed += slice_
                if elapsed >= timeout:
                    raise RunnerFailure(f"runner exceeded its {int(timeout)} s deadline")
                if on_tick:
                    on_tick()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    if len(out) > MAX_OUTPUT:
        raise RunnerFailure("runner output exceeded the limit")
    try:
        return json.loads(out or b"{}")
    except ValueError:
        raise RunnerFailure(f"runner returned unreadable output (exit {proc.returncode})")
