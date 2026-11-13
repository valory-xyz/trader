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

"""Tests for the lock-managed hash check, revert and relock guard."""

import json
import runpy
import subprocess  # nosec
import sys
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Tuple

import pytest
from hash_lock import (
    HashLine,
    Repository,
    find_hash_changes,
    find_non_hash_changes,
    is_lock_file,
    main,
    parse_component_config,
    parse_hash_lines,
    parse_packages_json,
)

SCRIPT = Path(__file__).parent / "hash_lock.py"
BASE32 = "abcdefghijklmnopqrstuvwxyz234567"


def cid(seed: int) -> str:
    """Build a distinct, well-formed IPFS CIDv1 for a seed.

    :param seed: any non-negative integer.
    :return: the hash.
    """
    digits = []
    for _ in range(52):
        seed, digit = divmod(seed * 7 + 3, 32)
        digits.append(BASE32[digit])
    return "bafybei" + "".join(digits)


SKILL = "skill/valory/my_skill/0.1.0"
AGENT = "agent/valory/my_agent/0.1.0"
SERVICE = "service/valory/my_service/0.1.0"
THIRD_PARTY = "skill/valory/abstract_round_abci/0.1.0"

# Hash names used by the fixture files; every name maps to a distinct CID.
H = {
    name: cid(index)
    for index, name in enumerate(
        [
            "skill",
            "agent",
            "service",
            "third_party",
            "fp_behaviours",
            "fp_init",
            "fp_new",
            "strategy",
            "override",
            "skill_v2",
            "agent_v2",
            "service_v2",
            "third_party_v2",
            "fp_behaviours_v2",
            "strategy_v2",
            "override_v2",
            "fp_init_v2",
        ],
        start=1,
    )
}


def packages_json(hashes: Dict[str, str]) -> str:
    """Render ``packages.json`` like ``autonomy packages lock`` does.

    :param hashes: the hash of each fixture package, by role.
    :return: the file content.
    """
    content = {
        "dev": {
            SKILL: hashes["skill"],
            AGENT: hashes["agent"],
            SERVICE: hashes["service"],
        },
        "third_party": {THIRD_PARTY: hashes["third_party"]},
    }
    return json.dumps(content, indent=4) + "\n"


def skill_yaml(hashes: Dict[str, str], extra_fingerprint: str = "") -> str:
    """Render a skill config.

    :param hashes: the hashes, by role.
    :param extra_fingerprint: extra fingerprint lines.
    :return: the file content.
    """
    return (
        "name: my_skill\n"
        "author: valory\n"
        "version: 0.1.0\n"
        "type: skill\n"
        "fingerprint:\n"
        f"  __init__.py: {hashes['fp_init']}\n"
        f"  behaviours.py: {hashes['fp_behaviours']}\n"
        f"{extra_fingerprint}"
        "fingerprint_ignore_patterns: []\n"
        "connections: []\n"
        "skills:\n"
        f"- valory/abstract_round_abci:0.1.0:{hashes['third_party']}\n"
        "models:\n"
        "  params:\n"
        "    args:\n"
        f"      file_hash_to_strategies: {{\"{hashes['strategy']}\": [\"kelly\"]}}\n"
    )


def agent_yaml(hashes: Dict[str, str]) -> str:
    """Render an agent config with an override document.

    :param hashes: the hashes, by role.
    :return: the file content.
    """
    return (
        "agent_name: my_agent\n"
        "author: valory\n"
        "fingerprint: {}\n"
        "skills:\n"
        f"- valory/abstract_round_abci:0.1.0:{hashes['third_party']}\n"
        f"- valory/my_skill:0.1.0:{hashes['skill']}\n"
        "customs: []\n"
        "---\n"
        f"public_id: valory/my_skill:0.1.0:{hashes['override']}\n"
        "type: skill\n"
    )


def service_yaml(hashes: Dict[str, str]) -> str:
    """Render a service config.

    :param hashes: the hashes, by role.
    :return: the file content.
    """
    return (
        "name: my_service\n"
        "author: valory\n"
        f"agent: valory/my_agent:0.1.0:{hashes['agent']}\n"
        "number_of_agents: 1\n"
        "---\n"
        "public_id: valory/my_skill:0.1.0\n"
        "type: skill\n"
    )


FILES: Dict[str, Callable[[Dict[str, str]], str]] = {
    "packages/packages.json": packages_json,
    "packages/valory/skills/my_skill/skill.yaml": skill_yaml,
    "packages/valory/agents/my_agent/aea-config.yaml": agent_yaml,
    "packages/valory/services/my_service/service.yaml": service_yaml,
}


def git(root: Path, *args: str) -> str:
    """Run git in a test repository.

    :param root: the repository root.
    :param args: the git arguments.
    :return: git's standard output.
    """
    return subprocess.run(  # nosec
        ["git", *args], cwd=root, check=True, capture_output=True, encoding="utf-8"
    ).stdout


def write(root: Path, path: str, text: str) -> None:
    """Write a file in a test repository with LF line endings.

    :param root: the repository root.
    :param path: the file path, relative to the root.
    :param text: the content.
    """
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    with open(file, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def read(root: Path, path: str) -> str:
    """Read a file in a test repository, keeping its line endings.

    :param root: the repository root.
    :param path: the file path, relative to the root.
    :return: the content.
    """
    with open(root / path, encoding="utf-8", newline="") as handle:
        return handle.read()


def write_packages(root: Path, hashes: Dict[str, str]) -> None:
    """Write every fixture package file.

    :param root: the repository root.
    :param hashes: the hashes, by role.
    """
    for path, render in FILES.items():
        write(root, path, render(hashes))


def with_hashes(**changes: str) -> Dict[str, str]:
    """Copy the base hashes with some roles changed.

    :param changes: the new hash of each changed role, by role.
    :return: the hashes.
    """
    return {**H, **changes}


@pytest.fixture(name="repo")
def fixture_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Create a repository whose ``main`` holds lock-consistent fixture packages.

    The working directory is a ``feature`` branch forked from ``main``.

    :param tmp_path: pytest's temporary directory.
    :param monkeypatch: pytest's monkeypatch fixture.
    :yield: the repository root.
    """
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "core.autocrlf", "false")
    write_packages(tmp_path, H)
    write(tmp_path, "README.md", "readme\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    git(tmp_path, "checkout", "-q", "-b", "feature")
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def run(capsys: pytest.CaptureFixture, *argv: str) -> Tuple[int, str]:
    """Run the command line and capture its output.

    :param capsys: pytest's capture fixture.
    :param argv: the arguments.
    :return: the exit code and the standard output.
    """
    code = main(list(argv))
    return code, capsys.readouterr().out


class TestIsLockFile:
    """Tests for ``is_lock_file``."""

    @pytest.mark.parametrize(
        "path",
        [
            "packages/packages.json",
            "packages/valory/skills/x/skill.yaml",
            "packages/valory/agents/x/aea-config.yaml",
            "packages/valory/services/x/service.yaml",
            "packages/valory/customs/x/component.yaml",
            "packages/valory/contracts/x/contract.yaml",
            "packages/valory/connections/x/connection.yaml",
            "packages/valory/protocols/x/protocol.yaml",
        ],
    )
    def test_lock_files(self, path: str) -> None:
        """Package configs and ``packages.json`` are lock files."""
        assert is_lock_file(path)

    @pytest.mark.parametrize(
        "path",
        [
            "README.md",
            "skill.yaml",
            "packages/valory/skills/x/behaviours.py",
            "packages/valory/skills/x/fsm_specification.yaml",
            "mints/01.json",
        ],
    )
    def test_other_files(self, path: str) -> None:
        """Other files are not lock files."""
        assert not is_lock_file(path)


class TestParsing:
    """Tests for the hash-line parsers."""

    def test_packages_json(self) -> None:
        """Both sections' entries are found, keyed by section and id."""
        lines = parse_packages_json(packages_json(H).splitlines())
        assert [(line.key, line.value) for line in lines] == [
            (("dev", SKILL), H["skill"]),
            (("dev", AGENT), H["agent"]),
            (("dev", SERVICE), H["service"]),
            (("third_party", THIRD_PARTY), H["third_party"]),
        ]
        assert all(line.package_id == line.key[1] for line in lines)

    def test_packages_json_entry_outside_section(self) -> None:
        """A hash entry before any section is not an entry."""
        assert not parse_packages_json([f'"x/y/z/0.1.0": "{H["skill"]}"'])

    def test_skill_config(self) -> None:
        """Fingerprints and dependencies are found; config values are not."""
        lines = parse_component_config(skill_yaml(H).splitlines())
        assert lines == [
            HashLine(("fingerprint", "__init__.py"), 5, H["fp_init"], None),
            HashLine(("fingerprint", "behaviours.py"), 6, H["fp_behaviours"], None),
            HashLine(
                ("skills", "valory/abstract_round_abci:0.1.0"),
                10,
                H["third_party"],
                THIRD_PARTY,
            ),
        ]

    def test_agent_config_stops_at_overrides(self) -> None:
        """Hashes in override documents are not lock-written."""
        lines = parse_component_config(agent_yaml(H).splitlines())
        assert [line.key for line in lines] == [
            ("skills", "valory/abstract_round_abci:0.1.0"),
            ("skills", "valory/my_skill:0.1.0"),
        ]
        assert lines[1].package_id == SKILL

    def test_service_agent_line(self) -> None:
        """The ``agent:`` line identifies the agent package."""
        lines = parse_component_config(service_yaml(H).splitlines())
        assert lines == [HashLine(("agent",), 2, H["agent"], AGENT)]

    def test_leading_document_marker(self) -> None:
        """A ``---`` on the first line opens the first document."""
        lines = parse_component_config(["---", f"agent: a/b:0.1.0:{H['agent']}"])
        assert lines == [HashLine(("agent",), 1, H["agent"], "agent/a/b/0.1.0")]

    def test_other_lines_in_hash_sections(self) -> None:
        """Lines without a hash inside hash sections are not hash lines."""
        lines = [
            "fingerprint:",
            "  # a comment",
            "  data.json: not-a-hash",
            "skills:",
            "- valory/unhashed:0.1.0",
        ]
        assert not parse_component_config(lines)

    def test_top_level_without_hash(self) -> None:
        """Top-level keys without a public id hold no hash."""
        assert not parse_component_config(["agent: valory/x:0.1.0", "name: x"])

    def test_dependency_types(self) -> None:
        """Each dependency section maps to its package type."""
        lines = parse_component_config(
            [
                "connections:",
                f"- valory/c:0.1.0:{H['skill']}",
                "contracts:",
                f"- valory/k:0.1.0:{H['skill']}",
                "protocols:",
                f"- open_aea/p:1.0.0:{H['skill']}",
                "customs:",
                f"- valory/u:0.1.0:{H['skill']}",
            ]
        )
        assert [line.package_id for line in lines] == [
            "connection/valory/c/0.1.0",
            "contract/valory/k/0.1.0",
            "protocol/open_aea/p/1.0.0",
            "custom/valory/u/0.1.0",
        ]

    def test_parse_dispatch(self) -> None:
        """``parse_hash_lines`` picks the parser by path."""
        assert parse_hash_lines("packages/packages.json", packages_json(H))
        assert parse_hash_lines("packages/a/skills/b/skill.yaml", skill_yaml(H))


class TestCheck:
    """Tests for the ``check`` command."""

    @pytest.mark.usefixtures("repo")
    def test_no_changes(self, capsys: pytest.CaptureFixture) -> None:
        """A branch without changes passes."""
        code, out = run(capsys, "check", "--base", "main")
        assert code == 0
        assert "No lock-managed hash values changed." in out

    def test_code_only_change(self, repo: Path, capsys: pytest.CaptureFixture) -> None:
        """Code changes without hash changes pass."""
        write(repo, "packages/valory/skills/my_skill/behaviours.py", "x = 1\n")
        write(repo, "README.md", "changed\n")
        assert run(capsys, "check", "--base", "main")[0] == 0

    def test_relocked_branch_fails(
        self, repo: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Every lock-managed hash value a local relock rewrote is reported."""
        write_packages(
            repo,
            with_hashes(
                skill=H["skill_v2"],
                agent=H["agent_v2"],
                service=H["service_v2"],
                fp_behaviours=H["fp_behaviours_v2"],
            ),
        )
        code, out = run(capsys, "check", "--base", "main")
        assert code == 1
        assert "rewrites 6 package hash value(s)" in out
        for location in [
            f"packages/packages.json:3: dev {SKILL}",
            f"packages/packages.json:4: dev {AGENT}",
            f"packages/packages.json:5: dev {SERVICE}",
            "aea-config.yaml:6: skills valory/my_skill:0.1.0",
            "service.yaml:3: agent",
            "skill.yaml:7: fingerprint behaviours.py",
        ]:
            assert location in out
        assert "hash_lock.py revert" in out

    def test_allowed_changes(self, repo: Path, capsys: pytest.CaptureFixture) -> None:
        """Third-party bumps, config hashes and new entries are allowed."""
        hashes = with_hashes(
            third_party=H["third_party_v2"],
            strategy=H["strategy_v2"],
            override=H["override_v2"],
        )
        write_packages(repo, hashes)
        write(
            repo,
            "packages/valory/skills/my_skill/skill.yaml",
            skill_yaml(hashes, extra_fingerprint=f"  new.py: {H['fp_new']}\n"),
        )
        new_package = json.loads(packages_json(hashes))
        new_package["dev"]["contract/valory/new/0.1.0"] = H["fp_new"]
        write(repo, "packages/packages.json", json.dumps(new_package, indent=4))
        write(
            repo,
            "packages/valory/contracts/new/contract.yaml",
            f"fingerprint:\n  contract.py: {H['fp_new']}\n",
        )
        code, out = run(capsys, "check", "--base", "main")
        assert (code, out) == (0, "No lock-managed hash values changed.\n")

    def test_staged_new_file(self, repo: Path, capsys: pytest.CaptureFixture) -> None:
        """A new package config staged for commit has no base values."""
        write(
            repo,
            "packages/valory/contracts/new/contract.yaml",
            f"fingerprint:\n  contract.py: {H['fp_new']}\n",
        )
        git(repo, "add", "-A")
        assert run(capsys, "check", "--base", "main")[0] == 0

    def test_deleted_file(self, repo: Path, capsys: pytest.CaptureFixture) -> None:
        """A deleted package config has no values left to check."""
        (repo / "packages/valory/services/my_service/service.yaml").unlink()
        assert run(capsys, "check", "--base", "main")[0] == 0

    def test_compares_with_merge_base(
        self, repo: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Hashes relocked on main after the fork point do not count."""
        git(repo, "checkout", "-q", "main")
        write_packages(repo, with_hashes(skill=H["skill_v2"]))
        git(repo, "commit", "-q", "-am", "chore: relock package hashes")
        git(repo, "checkout", "-q", "feature")
        assert run(capsys, "check", "--base", "main")[0] == 0

    def test_new_dev_package_dependency(
        self, repo: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A dependency on a package that only the branch makes ``dev`` counts."""
        git(repo, "checkout", "-q", "main")
        write(
            repo,
            "packages/valory/skills/my_skill/skill.yaml",
            skill_yaml(H) + f"customs:\n- valory/kelly:0.1.0:{H['fp_new']}\n",
        )
        git(repo, "commit", "-q", "-am", "depend on a third-party custom")
        git(repo, "checkout", "-q", "feature")
        git(repo, "merge", "-q", "main")
        content = json.loads(packages_json(H))
        content["dev"]["custom/valory/kelly/0.1.0"] = H["fp_init_v2"]
        write(repo, "packages/packages.json", json.dumps(content, indent=4))
        write(
            repo,
            "packages/valory/skills/my_skill/skill.yaml",
            skill_yaml(H) + f"customs:\n- valory/kelly:0.1.0:{H['fp_init_v2']}\n",
        )
        code, out = run(capsys, "check", "--base", "main")
        assert code == 1
        assert "customs valory/kelly:0.1.0" in out

    @pytest.mark.usefixtures("repo")
    def test_git_error(self, capsys: pytest.CaptureFixture) -> None:
        """An unknown base revision exits with code 2 and git's message."""
        assert main(["check", "--base", "no-such-branch"]) == 2
        assert "git merge-base no-such-branch HEAD failed" in capsys.readouterr().err


class TestRevert:
    """Tests for the ``revert`` command."""

    def test_reverts_only_lock_managed_values(
        self, repo: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Lock-managed values return to the base; everything else stays."""
        changed = with_hashes(
            skill=H["skill_v2"],
            agent=H["agent_v2"],
            service=H["service_v2"],
            fp_behaviours=H["fp_behaviours_v2"],
            third_party=H["third_party_v2"],
            strategy=H["strategy_v2"],
        )
        write_packages(repo, changed)
        code, out = run(capsys, "revert", "--base", "main")
        assert code == 0
        assert "Reverted 6 lock-managed hash value(s)." in out
        expected = with_hashes(
            third_party=H["third_party_v2"], strategy=H["strategy_v2"]
        )
        for path, render in FILES.items():
            assert read(repo, path) == render(expected)
        assert run(capsys, "check", "--base", "main")[0] == 0

    def test_keeps_line_endings(
        self, repo: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A file's line endings survive the revert."""
        path = "packages/valory/services/my_service/service.yaml"
        crlf = service_yaml(with_hashes(agent=H["agent_v2"])).replace("\n", "\r\n")
        write(repo, path, crlf)
        assert run(capsys, "revert", "--base", "main")[0] == 0
        assert read(repo, path) == service_yaml(H).replace("\n", "\r\n")

    @pytest.mark.usefixtures("repo")
    def test_nothing_to_revert(self, capsys: pytest.CaptureFixture) -> None:
        """Without changes, nothing is written."""
        code, out = run(capsys, "revert", "--base", "main")
        assert (code, out) == (0, "Reverted 0 lock-managed hash value(s).\n")


class TestGuard:
    """Tests for the ``guard`` command."""

    def commit_merge(self, repo: Path) -> None:
        """Commit a code change on main, as a merged PR leaves it before the relock.

        :param repo: the repository root.
        """
        git(repo, "checkout", "-q", "main")
        write(repo, "packages/valory/skills/my_skill/behaviours.py", "x = 2\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "merge PR")

    def relock(self, repo: Path) -> None:
        """Rewrite every hash the lock writes, as the relock would.

        :param repo: the repository root.
        """
        write_packages(
            repo,
            with_hashes(
                skill=H["skill_v2"],
                agent=H["agent_v2"],
                service=H["service_v2"],
                fp_behaviours=H["fp_behaviours_v2"],
            ),
        )
        write(
            repo,
            "packages/valory/skills/my_skill/skill.yaml",
            skill_yaml(
                with_hashes(fp_behaviours=H["fp_behaviours_v2"]),
                extra_fingerprint=f"  new.py: {H['fp_new']}\n",
            ),
        )

    @pytest.mark.usefixtures("repo")
    def test_no_changes(self, capsys: pytest.CaptureFixture) -> None:
        """An unchanged tree passes."""
        code, out = run(capsys, "guard")
        assert (code, out) == (0, "Only lock-written hash lines changed.\n")

    def test_relock_passes(self, repo: Path, capsys: pytest.CaptureFixture) -> None:
        """Changed, added and removed hash lines pass."""
        self.commit_merge(repo)
        self.relock(repo)
        assert run(capsys, "guard")[0] == 0
        write(
            repo,
            "packages/valory/skills/my_skill/skill.yaml",
            skill_yaml(H).replace(f"  __init__.py: {H['fp_init']}\n", ""),
        )
        assert run(capsys, "guard")[0] == 0

    @pytest.mark.parametrize(
        ("path", "old", "new", "expected"),
        [
            (
                "packages/valory/skills/my_skill/skill.yaml",
                H["strategy"],
                H["strategy_v2"],
                "skill.yaml:16:       file_hash_to_strategies",
            ),
            (
                "packages/valory/agents/my_agent/aea-config.yaml",
                H["override"],
                H["override_v2"],
                "aea-config.yaml:9: public_id: valory/my_skill",
            ),
            (
                "packages/valory/skills/my_skill/skill.yaml",
                "version: 0.1.0",
                "version: 0.2.0",
                "skill.yaml:3: version: 0.2.0",
            ),
        ],
    )
    def test_non_hash_line_fails(  # pylint: disable=too-many-arguments
        self,
        repo: Path,
        capsys: pytest.CaptureFixture,
        path: str,
        old: str,
        new: str,
        expected: str,
    ) -> None:
        """A changed line the lock does not write fails the guard."""
        self.relock(repo)
        write(repo, path, read(repo, path).replace(old, new))
        code, out = run(capsys, "guard")
        assert code == 1
        assert "The relock changed more than lock-written hash lines:" in out
        assert expected in out

    def test_removed_non_hash_line_fails(
        self, repo: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A removed line the lock does not write fails the guard."""
        path = "packages/valory/services/my_service/service.yaml"
        write(repo, path, read(repo, path).replace("number_of_agents: 1\n", ""))
        code, out = run(capsys, "guard")
        assert code == 1
        assert "service.yaml: removed line 4: number_of_agents: 1" in out

    def test_other_files_fail(self, repo: Path, capsys: pytest.CaptureFixture) -> None:
        """Changes outside lock files, new files and deletions fail the guard."""
        write(repo, "README.md", "changed\n")
        write(repo, "packages/valory/skills/my_skill/new.py", "y = 1\n")
        (repo / "packages/valory/services/my_service/service.yaml").unlink()
        code, out = run(capsys, "guard", "--base", "HEAD")
        assert code == 1
        problems: List[str] = out.splitlines()[1:]
        assert problems == [
            "  packages/valory/skills/my_skill/new.py: untracked file",
            "  README.md: not a file the lock writes",
            "  packages/valory/services/my_service/service.yaml: "
            "file added or deleted",
        ]


class TestRepository:
    """Tests for the git helpers that the commands do not reach."""

    def test_find_functions_take_a_revision(self, repo: Path) -> None:
        """The finders compare the working tree with any revision."""
        root = Repository(repo)
        assert not find_hash_changes(root, "HEAD")
        assert not find_non_hash_changes(root, "HEAD")

    def test_deleted_packages_json(self, repo: Path) -> None:
        """When the branch deletes ``packages.json``, the base names the ``dev`` packages."""
        write_packages(repo, with_hashes(skill=H["skill_v2"]))
        (repo / "packages/packages.json").unlink()
        changes = find_hash_changes(Repository(repo), "HEAD")
        assert [(change.path, change.hash_line.key) for change in changes] == [
            (
                "packages/valory/agents/my_agent/aea-config.yaml",
                ("skills", "valory/my_skill:0.1.0"),
            )
        ]


class TestCommandLine:
    """Tests for running the script as a program."""

    @pytest.mark.usefixtures("repo")
    def test_runs_as_script(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The script's entry point runs the command and exits with its code."""
        monkeypatch.setattr(sys, "argv", [str(SCRIPT), "check", "--base", "main"])
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_path(str(SCRIPT), run_name="__main__")
        assert exit_info.value.code == 0
        assert "No lock-managed hash values changed." in capsys.readouterr().out

    def test_requires_a_command(self, capsys: pytest.CaptureFixture) -> None:
        """A missing command is a usage error."""
        with pytest.raises(SystemExit) as exit_info:
            main([])
        assert exit_info.value.code == 2
        assert "required" in capsys.readouterr().err
