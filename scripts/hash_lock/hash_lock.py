#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""Keep the package hashes that ``autonomy packages lock`` writes out of pull requests.

The relock workflow (``.github/workflows/relock-main.yaml``) runs
``autonomy packages lock`` on ``main`` after each merge, so a pull request
leaves every lock-managed hash value as it found it. Two package PRs then no
longer conflict on the shared hash lines, and updating a PR from ``main``
stays a clean merge that keeps its approvals.

Lock-managed hash values are the ones the lock rewrites when a package of this
repository changes:

- the ``dev`` entries in ``packages/packages.json``;
- the ``fingerprint`` entries of a component config;
- the dependency entries (``- author/name:version:hash``) of a component
  config that point at a ``dev`` package;
- the ``agent:`` line of a service config.

A PR may still add entries (a new package, dependency or file) and bump
third-party hashes. Hashes inside configuration values, such as
``file_hash_to_strategies``, are not lock-managed: the lock does not update
them, so a PR keeps them current itself.

Usage, from anywhere in the repository::

    python scripts/hash_lock/hash_lock.py check   # fail on lock-managed hash changes
    python scripts/hash_lock/hash_lock.py revert  # restore them from the merge base
    python scripts/hash_lock/hash_lock.py guard --base HEAD

``check`` and ``revert`` compare the working tree with its merge base with
``--base`` (default ``origin/main``). ``guard`` is for the relock workflow: it
fails when the working tree differs from ``--base`` (default ``HEAD``) in
anything other than the hash lines the lock writes.
"""

import argparse
import difflib
import json
import re
import subprocess  # nosec
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

PACKAGES_JSON = "packages/packages.json"
COMPONENT_CONFIGS = frozenset(
    {
        "aea-config.yaml",
        "component.yaml",
        "connection.yaml",
        "contract.yaml",
        "protocol.yaml",
        "service.yaml",
        "skill.yaml",
    }
)
# The component config section that lists dependencies of each package type.
DEPENDENCY_SECTIONS = {
    "connections": "connection",
    "contracts": "contract",
    "customs": "custom",
    "protocols": "protocol",
    "skills": "skill",
}

HASH = r"bafybei[a-z2-7]+"
JSON_SECTION_RE = re.compile(r'^\s*"(?P<section>[a-z_]+)": \{\s*$')
JSON_ENTRY_RE = re.compile(rf'^\s*"(?P<id>[^"]+)": "(?P<hash>{HASH})",?\s*$')
TOP_LEVEL_RE = re.compile(r"^(?P<key>[A-Za-z_][\w-]*):(?: (?P<value>.*))?$")
FINGERPRINT_RE = re.compile(rf"^  (?P<path>\S+): (?P<hash>{HASH})$")
DEPENDENCY_RE = re.compile(
    rf"^- (?P<author>[\w-]+)/(?P<name>\w+):(?P<version>[^:\s]+):(?P<hash>{HASH})$"
)
PUBLIC_ID_RE = re.compile(
    rf"^(?P<author>[\w-]+)/(?P<name>\w+):(?P<version>[^:\s]+):(?P<hash>{HASH})$"
)

SCRIPT = "python scripts/hash_lock/hash_lock.py"


@dataclass(frozen=True)
class HashLine:
    """A line of a package file that holds a hash written by the lock."""

    # Identifies the entry across two versions of the same file.
    key: Tuple[str, ...]
    # 0-based line index in the file.
    index: int
    value: str
    # The package the hash identifies, as in ``packages.json``
    # (``type/author/name/version``), or ``None`` for a file fingerprint.
    package_id: Optional[str]


@dataclass(frozen=True)
class HashChange:
    """A lock-managed hash value that the working tree changed."""

    path: str
    hash_line: HashLine
    old_value: str


def is_lock_file(path: str) -> bool:
    """Tell whether ``autonomy packages lock`` writes hashes into a file.

    :param path: the file path, relative to the repository root.
    :return: whether the file is ``packages.json`` or a component config.
    """
    if path == PACKAGES_JSON:
        return True
    return path.startswith("packages/") and Path(path).name in COMPONENT_CONFIGS


def parse_packages_json(lines: Sequence[str]) -> List[HashLine]:
    """Find the hash lines of ``packages.json``.

    :param lines: the file's lines.
    :return: one hash line per package entry, keyed by section and package id.
    """
    hash_lines = []
    section = None
    for index, line in enumerate(lines):
        section_match = JSON_SECTION_RE.match(line)
        if section_match:
            section = section_match.group("section")
            continue
        entry = JSON_ENTRY_RE.match(line)
        if entry and section:
            package_id = entry.group("id")
            hash_lines.append(
                HashLine((section, package_id), index, entry.group("hash"), package_id)
            )
    return hash_lines


def parse_component_config(lines: Sequence[str]) -> List[HashLine]:
    """Find the hash lines of a component config.

    Only the first YAML document holds lock-written hashes. Later documents
    are configuration overrides, whose hashes the lock leaves alone.

    :param lines: the file's lines.
    :return: the fingerprint, dependency and ``agent:`` hash lines.
    """
    hash_lines = []
    section = None
    for index, line in enumerate(lines):
        if line == "---":
            if index:
                break
            continue
        top_level = TOP_LEVEL_RE.match(line)
        if top_level:
            section = top_level.group("key")
            agent = PUBLIC_ID_RE.match(top_level.group("value") or "")
            if section == "agent" and agent:
                package_id = "agent/{author}/{name}/{version}".format(
                    **agent.groupdict()
                )
                hash_lines.append(
                    HashLine(("agent",), index, agent.group("hash"), package_id)
                )
            continue
        if section == "fingerprint":
            fingerprint = FINGERPRINT_RE.match(line)
            if fingerprint:
                key = ("fingerprint", fingerprint.group("path"))
                hash_lines.append(HashLine(key, index, fingerprint.group("hash"), None))
        elif section in DEPENDENCY_SECTIONS:
            dependency = DEPENDENCY_RE.match(line)
            if dependency:
                parts = dependency.groupdict()
                key = (section, "{author}/{name}:{version}".format(**parts))
                package_id = "{}/{author}/{name}/{version}".format(
                    DEPENDENCY_SECTIONS[section], **parts
                )
                hash_lines.append(
                    HashLine(key, index, dependency.group("hash"), package_id)
                )
    return hash_lines


def parse_hash_lines(path: str, text: str) -> List[HashLine]:
    """Find the lines of a lock file that hold a hash written by the lock.

    :param path: the file path, relative to the repository root.
    :param text: the file's content.
    :return: the hash lines.
    """
    lines = text.splitlines()
    if path == PACKAGES_JSON:
        return parse_packages_json(lines)
    return parse_component_config(lines)


def is_lock_managed(hash_line: HashLine, dev_ids: Set[str]) -> bool:
    """Tell whether the lock owns a hash value, so a PR must leave it alone.

    :param hash_line: the hash line.
    :param dev_ids: the ids of this repository's own (``dev``) packages.
    :return: whether the hash fingerprints a file or identifies a ``dev`` package.
    """
    return hash_line.package_id is None or hash_line.package_id in dev_ids


class Repository:
    """The git repository the commands work on."""

    def __init__(self, root: Path) -> None:
        """Initialise the repository.

        :param root: the repository's top-level directory.
        """
        self.root = root

    def git(self, *args: str) -> str:
        """Run git in the repository.

        :param args: the git arguments.
        :return: git's standard output.
        """
        return subprocess.run(  # nosec
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            encoding="utf-8",
        ).stdout

    def merge_base(self, rev: str) -> str:
        """Find the commit where the current branch forked from a revision.

        :param rev: the revision, such as ``origin/main``.
        :return: the merge base of ``rev`` and ``HEAD``.
        """
        return self.git("merge-base", rev, "HEAD").strip()

    def changed_files(self, rev: str) -> List[str]:
        """List the tracked files whose working-tree content differs from a revision.

        :param rev: the revision.
        :return: the changed paths, including deleted ones.
        """
        return self.git("diff", "--name-only", "--no-renames", rev, "--").split()

    def untracked_files(self) -> List[str]:
        """List the files git does not track and does not ignore.

        :return: the untracked paths.
        """
        return self.git("ls-files", "--others", "--exclude-standard").split()

    def read_revision(self, rev: str, path: str) -> Optional[str]:
        """Read a file as it is at a revision.

        :param rev: the revision.
        :param path: the file path, relative to the repository root.
        :return: the content, or ``None`` when the file is absent at ``rev``.
        """
        try:
            return self.git("show", f"{rev}:{path}")
        except subprocess.CalledProcessError:
            return None

    def read_worktree(self, path: str) -> Optional[str]:
        """Read a file from the working tree.

        :param path: the file path, relative to the repository root.
        :return: the content, or ``None`` when the file is absent.
        """
        if not (self.root / path).is_file():
            return None
        return self.read_file(path)

    def read_file(self, path: str) -> str:
        """Read a file from the working tree, keeping its line endings.

        :param path: the file path, relative to the repository root.
        :return: the content.
        """
        with open(self.root / path, encoding="utf-8", newline="") as file:
            return file.read()

    def write_worktree(self, path: str, text: str) -> None:
        """Write a file in the working tree, keeping its line endings.

        :param path: the file path, relative to the repository root.
        :param text: the new content.
        """
        with open(self.root / path, "w", encoding="utf-8", newline="") as file:
            file.write(text)


def dev_package_ids(repo: Repository, rev: str) -> Set[str]:
    """Collect the ids of this repository's own packages.

    :param repo: the repository.
    :param rev: the revision to compare with the working tree.
    :return: the ``dev`` package ids at ``rev`` and in the working tree.
    """
    dev_ids: Set[str] = set()
    for text in (
        repo.read_revision(rev, PACKAGES_JSON),
        repo.read_worktree(PACKAGES_JSON),
    ):
        if text is not None:
            dev_ids.update(json.loads(text).get("dev", {}))
    return dev_ids


def find_hash_changes(repo: Repository, rev: str) -> List[HashChange]:
    """Find the lock-managed hash values the working tree changed.

    An entry counts only when it exists at ``rev`` and in the working tree,
    so new entries, removed entries and new files are allowed.

    :param repo: the repository.
    :param rev: the revision to compare with the working tree.
    :return: the changed values, in file and line order.
    """
    dev_ids = dev_package_ids(repo, rev)
    changes = []
    for path in sorted(repo.changed_files(rev)):
        if not is_lock_file(path):
            continue
        old_text = repo.read_revision(rev, path)
        new_text = repo.read_worktree(path)
        if old_text is None or new_text is None:
            continue
        old_values = {line.key: line.value for line in parse_hash_lines(path, old_text)}
        for hash_line in parse_hash_lines(path, new_text):
            old_value = old_values.get(hash_line.key)
            if old_value is None or old_value == hash_line.value:
                continue
            if is_lock_managed(hash_line, dev_ids):
                changes.append(HashChange(path, hash_line, old_value))
    return changes


def revert_hash_changes(repo: Repository, changes: Sequence[HashChange]) -> None:
    """Restore the old values of changed lock-managed hashes in the working tree.

    :param repo: the repository.
    :param changes: the changes to revert, as found by ``find_hash_changes``.
    """
    by_path: Dict[str, List[HashChange]] = {}
    for change in changes:
        by_path.setdefault(change.path, []).append(change)
    for path, path_changes in by_path.items():
        lines = repo.read_file(path).splitlines(keepends=True)
        for change in path_changes:
            index = change.hash_line.index
            lines[index] = lines[index].replace(
                change.hash_line.value, change.old_value, 1
            )
        repo.write_worktree(path, "".join(lines))


def non_hash_line_changes(path: str, old_text: str, new_text: str) -> Iterator[str]:
    """Describe the changed lines of a lock file that are not hash lines.

    :param path: the file path, relative to the repository root.
    :param old_text: the content before the change.
    :param new_text: the content after the change.
    :yield: one description per changed line that is not a hash line.
    """
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    old_hash_lines = {line.index for line in parse_hash_lines(path, old_text)}
    new_hash_lines = {line.index for line in parse_hash_lines(path, new_text)}
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        for index in range(old_start, old_end):
            if index not in old_hash_lines:
                yield f"{path}: removed line {index + 1}: {old_lines[index]}"
        for index in range(new_start, new_end):
            if index not in new_hash_lines:
                yield f"{path}:{index + 1}: {new_lines[index]}"


def find_non_hash_changes(repo: Repository, rev: str) -> List[str]:
    """Describe every working-tree change that is not a lock-written hash line.

    :param repo: the repository.
    :param rev: the revision to compare with the working tree.
    :return: one description per offending change.
    """
    problems = [f"{path}: untracked file" for path in repo.untracked_files()]
    for path in sorted(repo.changed_files(rev)):
        if not is_lock_file(path):
            problems.append(f"{path}: not a file the lock writes")
            continue
        old_text = repo.read_revision(rev, path)
        new_text = repo.read_worktree(path)
        if old_text is None or new_text is None:
            problems.append(f"{path}: file added or deleted")
            continue
        problems.extend(non_hash_line_changes(path, old_text, new_text))
    return problems


def describe(change: HashChange) -> str:
    """Describe a changed hash value for the command output.

    :param change: the change.
    :return: the location and the entry it belongs to.
    """
    entry = " ".join(change.hash_line.key)
    return f"  {change.path}:{change.hash_line.index + 1}: {entry}"


def run_check(repo: Repository, base: str) -> int:
    """Fail when the working tree changes a lock-managed hash value.

    :param repo: the repository.
    :param base: the branch the PR targets.
    :return: the exit code.
    """
    changes = find_hash_changes(repo, repo.merge_base(base))
    if not changes:
        print("No lock-managed hash values changed.")
        return 0
    print(
        f"This change rewrites {len(changes)} package hash value(s) that the "
        "relock on main owns:"
    )
    for change in changes:
        print(describe(change))
    print(
        "\nHashes are relocked on main after each merge, so pull requests leave "
        f"them unchanged. To drop these changes, run\n\n    {SCRIPT} revert\n\n"
        "and commit the result. Add --base <branch> when the PR targets a branch "
        "other than main."
    )
    return 1


def run_revert(repo: Repository, base: str) -> int:
    """Restore the lock-managed hash values the working tree changed.

    :param repo: the repository.
    :param base: the branch the PR targets.
    :return: the exit code.
    """
    changes = find_hash_changes(repo, repo.merge_base(base))
    revert_hash_changes(repo, changes)
    print(f"Reverted {len(changes)} lock-managed hash value(s).")
    for change in changes:
        print(describe(change))
    return 0


def run_guard(repo: Repository, base: str) -> int:
    """Fail when the working tree changes anything but lock-written hash lines.

    :param repo: the repository.
    :param base: the commit the lock ran on.
    :return: the exit code.
    """
    problems = find_non_hash_changes(repo, base)
    if not problems:
        print("Only lock-written hash lines changed.")
        return 0
    print("The relock changed more than lock-written hash lines:")
    for problem in problems:
        print(f"  {problem}")
    return 1


COMMANDS = {
    "check": (run_check, "origin/main", "fail on lock-managed hash value changes"),
    "revert": (run_revert, "origin/main", "restore lock-managed hash values"),
    "guard": (run_guard, "HEAD", "fail on changes other than lock-written hashes"),
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run a command.

    :param argv: the command-line arguments, without the program name.
    :return: the exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name, (_, default_base, summary) in COMMANDS.items():
        command = commands.add_parser(name, help=summary, description=summary)
        command.add_argument(
            "--base",
            default=default_base,
            help=f"the revision to compare with (default: {default_base})",
        )
    args = parser.parse_args(argv)
    try:
        top_level = subprocess.run(  # nosec
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            encoding="utf-8",
        ).stdout.strip()
        run, _, _ = COMMANDS[args.command]
        return run(Repository(Path(top_level)), args.base)
    except subprocess.CalledProcessError as error:
        print(f"git {' '.join(error.cmd[1:])} failed: {error.stderr}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
