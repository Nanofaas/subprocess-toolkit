from __future__ import annotations

import json
from pathlib import Path

from shellcraft.backend import RecordingShell
from shellcraft.fileutil import read_json_field, write_json_file, wrap_payload
from shellcraft.runners import CommandRunner, ContainerRuntimeOps, KubectlOps, PlannedCommand


def test_command_runner_delegates_to_shell() -> None:
    shell = RecordingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    result = runner.run(["echo", "hi"], dry_run=True)
    assert result.command == ["echo", "hi"]


def test_command_runner_records_commands() -> None:
    shell = RecordingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    runner.run(["echo", "a"], dry_run=True)
    runner.run(["echo", "b"], dry_run=True)
    assert shell.commands == [["echo", "a"], ["echo", "b"]]


def test_planned_command_run_delegates_to_runner() -> None:
    shell = RecordingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    cmd = PlannedCommand(command=["ls"], cwd=Path("/tmp"))
    cmd.run(runner, dry_run=True)
    assert shell.commands == [["ls"]]


def test_container_runtime_ops_build_uses_tag() -> None:
    shell = RecordingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    ops = ContainerRuntimeOps(runner=runner, runtime="docker")
    ops.build(tag="my-image:test", context=Path("/repo/app"), dry_run=True)
    assert any("my-image:test" in " ".join(cmd) for cmd in shell.commands)


def test_container_runtime_ops_build_passes_build_args() -> None:
    shell = RecordingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    ops = ContainerRuntimeOps(runner=runner, runtime="docker")
    ops.build(tag="img", context=Path("/ctx"), build_args={"FOO": "bar"}, dry_run=True)
    rendered = " ".join(shell.commands[0])
    assert "--build-arg" in rendered
    assert "FOO=bar" in rendered


def test_container_runtime_ops_remove_includes_name() -> None:
    shell = RecordingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    ops = ContainerRuntimeOps(runner=runner, runtime="docker")
    ops.remove("my-container", dry_run=True)
    assert any("my-container" in " ".join(cmd) for cmd in shell.commands)


def test_container_runtime_ops_uses_configured_runtime() -> None:
    shell = RecordingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    ops = ContainerRuntimeOps(runner=runner, runtime="podman")
    ops.build(tag="img", context=Path("/ctx"), dry_run=True)
    assert shell.commands[0][0] == "podman"


def test_kubectl_ops_apply_includes_manifest() -> None:
    shell = RecordingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    ops = KubectlOps(runner=runner)
    ops.apply(Path("/tmp/manifest.yaml"), dry_run=True)
    assert any("/tmp/manifest.yaml" in " ".join(cmd) for cmd in shell.commands)


def test_kubectl_ops_respects_kubeconfig() -> None:
    shell = RecordingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    ops = KubectlOps(runner=runner, kubeconfig="/home/user/.kube/config")
    ops.apply(Path("/tmp/manifest.yaml"), dry_run=True)
    rendered = [" ".join(cmd) for cmd in shell.commands]
    assert any("/home/user/.kube/config" in r for r in rendered)


def test_kubectl_ops_delete_adds_ignore_not_found() -> None:
    shell = RecordingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    ops = KubectlOps(runner=runner)
    ops.delete("deployment", "my-app", dry_run=True)
    rendered = " ".join(shell.commands[0])
    assert "--ignore-not-found" in rendered


def test_read_json_field_extracts_nested_value(tmp_path: Path) -> None:
    f = tmp_path / "data.json"
    f.write_text('{"a": {"b": "hello"}}', encoding="utf-8")
    assert read_json_field(f, "a.b") == "hello"


def test_write_json_file_roundtrips(tmp_path: Path) -> None:
    f = tmp_path / "out.json"
    write_json_file(f, {"name": "test", "value": 42})
    assert read_json_field(f, "name") == "test"
    assert read_json_field(f, "value") == 42


def test_wrap_payload_wraps_in_input_key(tmp_path: Path) -> None:
    payload = tmp_path / "payload.json"
    payload.write_text('{"x": 1}', encoding="utf-8")
    out = tmp_path / "wrapped.json"
    wrap_payload(payload, out)
    data = json.loads(out.read_text())
    assert data == {"input": {"x": 1}}
