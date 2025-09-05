#!/usr/bin/env python3
import platform
import subprocess
import sys
import time
import os
import shlex


def main():
    timeout = 20
    search = "Starting AEA"
    cmd = "bash -c 'cd ./agent && ../dist/agent_runner_bin -s run'"

    print(f"Running command:\n  {cmd}\nWaiting up to {timeout}s for '{search}'...")

    # Copy env and set your variable
    env = os.environ.copy()
    env["SKILL_TRADER_ABCI_MODELS_PARAMS_ARGS_STORE_PATH"] = "/tmp"

    # Cross-platform handling
    system = platform.system()
    if system == "Windows":
        # Split command safely, set working dir instead of `cd`
        parts = shlex.split(cmd)
        if parts[0] == "cd":
            workdir = parts[1]
            exec_cmd = parts[3:]  # skip "&&"
            cwd = workdir
        else:
            exec_cmd = parts
            cwd = None

        proc = subprocess.Popen(
            exec_cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            shell=True,
        )
    else:
        # On Linux/macOS, run normally through bash
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )

    start = time.time()
    found = False
    try:
        for line in iter(proc.stdout.readline, ""):
            try:
                sys.stdout.write(line)
                sys.stdout.flush()
            except UnicodeEncodeError:
                sys.stdout.write(line.encode("utf-8", errors="ignore").decode("utf-8"))

            if search in line:
                found = True
                break
            if time.time() - start > timeout:
                break
    finally:
        proc.terminate()

    if found:
        print(f"[OK] Found '{search}' within {timeout}s")
        sys.exit(0)
    else:
        print(f"[FAIL] Did not find '{search}' within {timeout}s")
        sys.exit(1)


if __name__ == "__main__":
    main()
