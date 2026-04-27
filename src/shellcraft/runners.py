from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from shellcraft.backend import ShellBackend, ShellExecutionResult, SubprocessShell


@dataclass
class CommandRunner:
    """Couples a ShellBackend with a working-directory root."""

    shell: ShellBackend = field(default_factory=SubprocessShell)
    repo_root: Path = field(default_factory=Path.cwd)

    def run(
        self,
        command: list[str],
        *,
        dry_run: bool = False,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> ShellExecutionResult:
        return self.shell.run(
            command,
            cwd=cwd or self.repo_root,
            env=env,
            dry_run=dry_run,
        )


@dataclass(frozen=True)
class PlannedCommand:
    command: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)

    def run(self, runner: CommandRunner, *, dry_run: bool = False) -> ShellExecutionResult:
        return runner.run(self.command, cwd=self.cwd, env=self.env, dry_run=dry_run)


@dataclass
class ContainerRuntimeOps:
    """Docker-compatible runtime operations (docker / podman / nerdctl)."""

    runner: CommandRunner
    runtime: str = "docker"

    def build(
        self,
        tag: str,
        context: Path,
        *,
        dockerfile: Path | None = None,
        build_args: dict[str, str] | None = None,
        dry_run: bool = False,
    ) -> ShellExecutionResult:
        command = [self.runtime, "build", "-t", tag]
        if dockerfile is not None:
            command.extend(["-f", str(dockerfile)])
        for key, value in (build_args or {}).items():
            command.extend(["--build-arg", f"{key}={value}"])
        command.append(str(context))
        return self.runner.run(command, dry_run=dry_run)

    def remove(self, *names: str, force: bool = True, dry_run: bool = False) -> ShellExecutionResult:
        command = [self.runtime, "rm"]
        if force:
            command.append("-f")
        command.extend(names)
        return self.runner.run(command, dry_run=dry_run)

    def run_container(
        self,
        image: str,
        *,
        name: str | None = None,
        detach: bool = False,
        ports: dict[int, int] | None = None,
        env: dict[str, str] | None = None,
        dry_run: bool = False,
    ) -> ShellExecutionResult:
        command = [self.runtime, "run"]
        if detach:
            command.append("-d")
        if name:
            command.extend(["--name", name])
        for host_port, container_port in (ports or {}).items():
            command.extend(["-p", f"{host_port}:{container_port}"])
        for key, value in (env or {}).items():
            command.extend(["-e", f"{key}={value}"])
        command.append(image)
        return self.runner.run(command, dry_run=dry_run)

    def list_containers(
        self,
        *,
        name_filter: str | None = None,
        all_containers: bool = False,
        format_str: str | None = None,
        dry_run: bool = False,
    ) -> ShellExecutionResult:
        command = [self.runtime, "ps"]
        if all_containers:
            command.append("-a")
        if name_filter:
            command.extend(["--filter", f"name={name_filter}"])
        if format_str:
            command.extend(["--format", format_str])
        return self.runner.run(command, dry_run=dry_run)

    def push(self, tag: str, *, dry_run: bool = False) -> ShellExecutionResult:
        return self.runner.run([self.runtime, "push", tag], dry_run=dry_run)


@dataclass
class KubectlOps:
    """kubectl operations with optional kubeconfig and namespace binding."""

    runner: CommandRunner
    kubeconfig: str | None = None
    namespace: str | None = None

    def _base(self) -> list[str]:
        command = ["kubectl"]
        if self.kubeconfig:
            command.extend(["--kubeconfig", self.kubeconfig])
        if self.namespace:
            command.extend(["-n", self.namespace])
        return command

    def apply(self, manifest: Path, *, dry_run: bool = False) -> ShellExecutionResult:
        return self.runner.run([*self._base(), "apply", "-f", str(manifest)], dry_run=dry_run)

    def delete(
        self,
        resource: str,
        name: str,
        *,
        ignore_not_found: bool = True,
        dry_run: bool = False,
    ) -> ShellExecutionResult:
        command = [*self._base(), "delete", resource, name]
        if ignore_not_found:
            command.append("--ignore-not-found")
        return self.runner.run(command, dry_run=dry_run)

    def rollout_restart(
        self, resource: str, name: str, *, dry_run: bool = False
    ) -> ShellExecutionResult:
        return self.runner.run(
            [*self._base(), "rollout", "restart", f"{resource}/{name}"],
            dry_run=dry_run,
        )

    def exec(self, pod: str, command: str, *, shell: str = "bash", dry_run: bool = False) -> ShellExecutionResult:
        return self.runner.run(
            [*self._base(), "exec", pod, "--", shell, "-lc", command],
            dry_run=dry_run,
        )
