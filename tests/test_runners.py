from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from shellcraft.backend import (
    RecordingShell,
    ShellBackend,
    ShellExecutionResult,
)
from shellcraft.fileutil import read_json_field, wrap_payload, write_json_file
from shellcraft.runners import (
    CommandRunner,
    ContainerRuntimeOps,
    KubectlOps,
    PlannedCommand,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def shell() -> RecordingShell:
    return RecordingShell()


@pytest.fixture
def runner(shell: RecordingShell) -> CommandRunner:
    return CommandRunner(shell=shell, repo_root=Path("/repo"))


@pytest.fixture
def docker(runner: CommandRunner) -> ContainerRuntimeOps:
    return ContainerRuntimeOps(runner=runner, runtime="docker")


@pytest.fixture
def kubectl(runner: CommandRunner) -> KubectlOps:
    return KubectlOps(runner=runner)


def only(shell: RecordingShell) -> list[str]:
    """Return the single command recorded, failing if there was not exactly one."""
    assert len(shell.commands) == 1, f"expected one command, got {shell.commands}"
    return shell.commands[0]


class CapturingShell(ShellBackend):
    """Records the full call, including cwd and env, which RecordingShell drops."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        dry_run: bool = False,
    ) -> ShellExecutionResult:
        self.calls.append(
            {"command": command, "cwd": cwd, "env": env, "dry_run": dry_run}
        )
        return ShellExecutionResult(command=command, return_code=0, env=env or {})


# ---------------------------------------------------------------------------
# CommandRunner
# ---------------------------------------------------------------------------


def test_command_runner_delegates_to_shell(shell: RecordingShell) -> None:
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    result = runner.run(["echo", "hi"], dry_run=True)
    assert result.command == ["echo", "hi"]
    assert only(shell) == ["echo", "hi"]


def test_command_runner_records_commands(shell: RecordingShell) -> None:
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    runner.run(["echo", "a"], dry_run=True)
    runner.run(["echo", "b"], dry_run=True)
    assert shell.commands == [["echo", "a"], ["echo", "b"]]


def test_command_runner_defaults_cwd_to_repo_root() -> None:
    shell = CapturingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    runner.run(["ls"])
    assert shell.calls[0]["cwd"] == Path("/repo")


def test_command_runner_explicit_cwd_overrides_repo_root() -> None:
    shell = CapturingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    runner.run(["ls"], cwd=Path("/elsewhere"))
    assert shell.calls[0]["cwd"] == Path("/elsewhere")


def test_command_runner_forwards_env_and_dry_run() -> None:
    shell = CapturingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    runner.run(["ls"], env={"A": "1"}, dry_run=True)
    assert shell.calls[0]["env"] == {"A": "1"}
    assert shell.calls[0]["dry_run"] is True


# ---------------------------------------------------------------------------
# PlannedCommand
# ---------------------------------------------------------------------------


def test_planned_command_run_delegates_to_runner(shell: RecordingShell) -> None:
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    cmd = PlannedCommand(command=["ls"], cwd=Path("/tmp"))
    cmd.run(runner, dry_run=True)
    assert only(shell) == ["ls"]


def test_planned_command_carries_its_own_cwd_and_env() -> None:
    shell = CapturingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    cmd = PlannedCommand(command=["ls"], cwd=Path("/planned"), env={"X": "y"})
    cmd.run(runner)
    assert shell.calls[0]["cwd"] == Path("/planned")
    assert shell.calls[0]["env"] == {"X": "y"}


def test_planned_command_is_frozen() -> None:
    cmd = PlannedCommand(command=["ls"], cwd=Path("/tmp"))
    with pytest.raises(FrozenInstanceError):
        cmd.cwd = Path("/other")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ContainerRuntimeOps.build
# ---------------------------------------------------------------------------


def test_build_without_optional_arguments(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.build(tag="img:1", context=Path("/ctx"))
    assert only(shell) == ["docker", "build", "-t", "img:1", "/ctx"]


def test_build_includes_dockerfile_when_given(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.build(
        tag="img", context=Path("/ctx"), dockerfile=Path("/ctx/Dockerfile.dev")
    )
    assert only(shell) == [
        "docker",
        "build",
        "-t",
        "img",
        "-f",
        "/ctx/Dockerfile.dev",
        "/ctx",
    ]


def test_build_passes_each_build_arg(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.build(tag="img", context=Path("/ctx"), build_args={"A": "1", "B": "2"})
    assert only(shell) == [
        "docker",
        "build",
        "-t",
        "img",
        "--build-arg",
        "A=1",
        "--build-arg",
        "B=2",
        "/ctx",
    ]


def test_build_uses_the_configured_runtime() -> None:
    shell = RecordingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    ops = ContainerRuntimeOps(runner=runner, runtime="nerdctl")
    ops.build(tag="img", context=Path("/ctx"))
    assert only(shell)[0] == "nerdctl"


# ---------------------------------------------------------------------------
# ContainerRuntimeOps.remove
# ---------------------------------------------------------------------------


def test_remove_forces_by_default(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.remove("c1")
    assert only(shell) == ["docker", "rm", "-f", "c1"]


def test_remove_without_force_omits_the_flag(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.remove("c1", force=False)
    assert only(shell) == ["docker", "rm", "c1"]


def test_remove_accepts_several_names(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.remove("c1", "c2", "c3")
    assert only(shell) == ["docker", "rm", "-f", "c1", "c2", "c3"]


# ---------------------------------------------------------------------------
# ContainerRuntimeOps.run_container
# ---------------------------------------------------------------------------


def test_run_container_minimal(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.run_container("img:latest")
    assert only(shell) == ["docker", "run", "img:latest"]


def test_run_container_with_all_options(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.run_container(
        "img:latest",
        name="app",
        detach=True,
        ports={8080: 80},
        env={"MODE": "prod"},
    )
    assert only(shell) == [
        "docker",
        "run",
        "-d",
        "--name",
        "app",
        "-p",
        "8080:80",
        "-e",
        "MODE=prod",
        "img:latest",
    ]


def test_run_container_emits_one_flag_per_port_and_env(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.run_container("img", ports={80: 80, 443: 443}, env={"A": "1", "B": "2"})
    assert only(shell) == [
        "docker",
        "run",
        "-p",
        "80:80",
        "-p",
        "443:443",
        "-e",
        "A=1",
        "-e",
        "B=2",
        "img",
    ]


def test_run_container_detach_false_has_no_d_flag(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.run_container("img", detach=False)
    assert "-d" not in only(shell)


# ---------------------------------------------------------------------------
# ContainerRuntimeOps.list_containers / push
# ---------------------------------------------------------------------------


def test_list_containers_minimal(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.list_containers()
    assert only(shell) == ["docker", "ps"]


def test_list_containers_with_all_flags(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.list_containers(all_containers=True, name_filter="app", format_str="{{.ID}}")
    assert only(shell) == [
        "docker",
        "ps",
        "-a",
        "--filter",
        "name=app",
        "--format",
        "{{.ID}}",
    ]


def test_list_containers_omits_empty_filters(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.list_containers(name_filter=None, format_str=None)
    assert only(shell) == ["docker", "ps"]


def test_push_tags_to_the_registry(
    docker: ContainerRuntimeOps, shell: RecordingShell
) -> None:
    docker.push("registry.example.com/app:1")
    assert only(shell) == ["docker", "push", "registry.example.com/app:1"]


# ---------------------------------------------------------------------------
# KubectlOps
# ---------------------------------------------------------------------------


def test_kubectl_apply_without_bindings(
    kubectl: KubectlOps, shell: RecordingShell
) -> None:
    kubectl.apply(Path("/tmp/manifest.yaml"))
    assert only(shell) == ["kubectl", "apply", "-f", "/tmp/manifest.yaml"]


def test_kubectl_apply_with_kubeconfig_and_namespace(
    runner: CommandRunner, shell: RecordingShell
) -> None:
    kubectl = KubectlOps(
        runner=runner, kubeconfig="/home/u/.kube/config", namespace="staging"
    )
    kubectl.apply(Path("/m.yaml"))
    assert only(shell) == [
        "kubectl",
        "--kubeconfig",
        "/home/u/.kube/config",
        "-n",
        "staging",
        "apply",
        "-f",
        "/m.yaml",
    ]


def test_kubectl_namespace_alone(runner: CommandRunner, shell: RecordingShell) -> None:
    kubectl = KubectlOps(runner=runner, namespace="prod")
    kubectl.apply(Path("/m.yaml"))
    assert only(shell) == ["kubectl", "-n", "prod", "apply", "-f", "/m.yaml"]


def test_kubectl_kubeconfig_alone(runner: CommandRunner, shell: RecordingShell) -> None:
    kubectl = KubectlOps(runner=runner, kubeconfig="/k")
    kubectl.apply(Path("/m.yaml"))
    assert only(shell) == [
        "kubectl",
        "--kubeconfig",
        "/k",
        "apply",
        "-f",
        "/m.yaml",
    ]


def test_kubectl_delete_defaults_to_ignore_not_found(
    kubectl: KubectlOps, shell: RecordingShell
) -> None:
    kubectl.delete("deployment", "my-app")
    assert only(shell) == [
        "kubectl",
        "delete",
        "deployment",
        "my-app",
        "--ignore-not-found",
    ]


def test_kubectl_delete_can_fail_on_missing(
    kubectl: KubectlOps, shell: RecordingShell
) -> None:
    kubectl.delete("deployment", "my-app", ignore_not_found=False)
    assert only(shell) == ["kubectl", "delete", "deployment", "my-app"]


def test_kubectl_rollout_restart_joins_resource_and_name(
    kubectl: KubectlOps, shell: RecordingShell
) -> None:
    kubectl.rollout_restart("deployment", "my-app")
    assert only(shell) == ["kubectl", "rollout", "restart", "deployment/my-app"]


def test_kubectl_exec_uses_bash_by_default(
    kubectl: KubectlOps, shell: RecordingShell
) -> None:
    kubectl.exec("pod-1", "curl -s localhost:80 | head -1")
    assert only(shell) == [
        "kubectl",
        "exec",
        "pod-1",
        "--",
        "bash",
        "-lc",
        "curl -s localhost:80 | head -1",
    ]


def test_kubectl_exec_honours_the_shell_argument(
    kubectl: KubectlOps, shell: RecordingShell
) -> None:
    kubectl.exec("pod-1", "ls", shell="sh")
    assert only(shell) == ["kubectl", "exec", "pod-1", "--", "sh", "-lc", "ls"]


def test_kubectl_exec_keeps_the_command_out_of_the_local_argv(
    kubectl: KubectlOps, shell: RecordingShell
) -> None:
    """The command string must stay one argv element, not be split on spaces."""
    kubectl.exec("pod-1", "a b c")
    assert only(shell)[-1] == "a b c"


def test_every_operation_forwards_dry_run() -> None:
    """dry_run must reach the backend, not be swallowed by a builder."""
    shell = CapturingShell()
    runner = CommandRunner(shell=shell, repo_root=Path("/repo"))
    docker = ContainerRuntimeOps(runner=runner)
    kubectl = KubectlOps(runner=runner)

    docker.build(tag="i", context=Path("/c"), dry_run=True)
    docker.remove("c", dry_run=True)
    docker.run_container("i", dry_run=True)
    docker.list_containers(dry_run=True)
    docker.push("i", dry_run=True)
    kubectl.apply(Path("/m.yaml"), dry_run=True)
    kubectl.delete("deployment", "d", dry_run=True)
    kubectl.rollout_restart("deployment", "d", dry_run=True)
    kubectl.exec("pod", "ls", dry_run=True)

    assert len(shell.calls) == 9
    assert all(call["dry_run"] is True for call in shell.calls)


# ---------------------------------------------------------------------------
# fileutil
# ---------------------------------------------------------------------------


def test_read_json_field_extracts_nested_value(tmp_path: Path) -> None:
    f = tmp_path / "data.json"
    f.write_text('{"a": {"b": "hello"}}', encoding="utf-8")
    assert read_json_field(f, "a.b") == "hello"


def test_read_json_field_indexes_lists(tmp_path: Path) -> None:
    f = tmp_path / "data.json"
    f.write_text('{"items": [{"id": "first"}, {"id": "second"}]}', encoding="utf-8")
    assert read_json_field(f, "items.1.id") == "second"


def test_read_json_field_ignores_empty_segments(tmp_path: Path) -> None:
    f = tmp_path / "data.json"
    f.write_text('{"a": {"b": 1}}', encoding="utf-8")
    assert read_json_field(f, "a..b") == 1


def test_write_json_file_roundtrips(tmp_path: Path) -> None:
    f = tmp_path / "out.json"
    write_json_file(f, {"name": "test", "value": 42})
    assert read_json_field(f, "name") == "test"
    assert read_json_field(f, "value") == 42


def test_write_json_file_sorts_keys(tmp_path: Path) -> None:
    f = tmp_path / "out.json"
    write_json_file(f, {"b": 1, "a": 2})
    assert f.read_text(encoding="utf-8").index('"a"') < f.read_text(
        encoding="utf-8"
    ).index('"b"')


def test_wrap_payload_wraps_in_input_key(tmp_path: Path) -> None:
    payload = tmp_path / "payload.json"
    payload.write_text('{"x": 1}', encoding="utf-8")
    out = tmp_path / "wrapped.json"
    wrap_payload(payload, out)
    data = json.loads(out.read_text())
    assert data == {"input": {"x": 1}}
