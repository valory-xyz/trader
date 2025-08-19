#!/usr/bin/env python3
from importlib.metadata import distributions
from aea.cli.utils.context import Context
from aea.cli.utils.config import (
    try_to_load_agent_config,
)
import os
from importlib.metadata import distributions
from pathlib import Path


def get_modules_from_dist(dist):
    """Try to get top-level modules from dist metadata, fallback to directory names."""
    modules = []

    # 1. Try top_level.txt
    try:
        top_level = dist.read_text("top_level.txt")
        if top_level:
            modules.extend([m.strip() for m in top_level.splitlines() if m.strip()])
    except FileNotFoundError:
        pass

    # 2. Fallback: look in site-packages directory
    if not modules:
        for path in dist.files or []:
            # Only consider first-level packages/modules

            if ".dist-info" in str(path):
                continue
            parts = Path(path).parts
            if len(parts) == 1 and parts[0].endswith(".py"):
                name = parts[0]
                modules.append(name[:-3])  # strip .py
            if len(parts) == 2 and parts[1] == "__init__.py":
                name = parts[0]
                modules.append(name)
    return sorted(set(modules))


def get_modules():
    os.chdir("agent")
    ctx = Context(cwd=".", verbosity="debug", registry_path=".")
    try_to_load_agent_config(ctx)
    deps = [i.replace("-", "_") for i in ctx.get_dependencies().keys()]
    all_modules = []
    for dist in distributions():
        dist_name = dist.metadata["Name"].lower().replace("-", "_")
        if dist_name in deps:
            modules = get_modules_from_dist(dist)
            for mod in modules:
                all_modules.append(mod)
    all_modules = list(sorted(all_modules))
    return all_modules


def modules_filter(modules):
    black_list = [
        "pytest",
        "pytest_asyncio",
        "_pytest",
        "py",
        "hypothesis",
        "Crypto",
        "_yaml",
    ]
    return [i for i in modules if i not in black_list]


def main():
    all_modules = modules_filter(get_modules())
    print(
        " ".join([f"--hidden-import {m} --collect-all {m}" for m in all_modules]),
        end="",
    )


if __name__ == "__main__":
    main()
