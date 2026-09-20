"""Typed command builders for container runtimes and kubectl.

Every operation returns a :class:`~subprocess_toolkit.backend.ShellExecutionResult` and
accepts ``dry_run``, so a plan can be rendered and reviewed before anything is
executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from subprocess_toolkit.backend import (
    ShellBackend,
    ShellExecutionResult,
    SubprocessShell,
)


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
        """Run command through the backend, defaulting to repo_root as cwd."""
        return self.shell.run(
            command,
            cwd=cwd or self.repo_root,
            env=env,
            dry_run=dry_run,
        )


@dataclass(frozen=True)
class PlannedCommand:
    """A command captured with the cwd and env it should run under.

    Deferring execution this way lets a caller collect commands first and run
    them later, against a different runner.
    """

    command: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)

    def run(
        self, runner: CommandRunner, *, dry_run: bool = False
    ) -> ShellExecutionResult:
        """Execute the planned command using runner."""
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
        """Build context and tag the resulting image."""
        command = [self.runtime, "build", "-t", tag]
        if dockerfile is not None:
            command.extend(["-f", str(dockerfile)])
        for key, value in (build_args or {}).items():
            command.extend(["--build-arg", f"{key}={value}"])
        command.append(str(context))
        return self.runner.run(command, dry_run=dry_run)

    def remove(
        self, *names: str, force: bool = True, dry_run: bool = False
    ) -> ShellExecutionResult:
        """Remove one or more containers by name."""
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
        """Start a container from image.

        ``ports`` maps host port to container port, and ``env`` is passed to the
        container as ``-e`` assignments.
        """
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
        """List containers, optionally including stopped ones."""
        command = [self.runtime, "ps"]
        if all_containers:
            command.append("-a")
        if name_filter:
            command.extend(["--filter", f"name={name_filter}"])
        if format_str:
            command.extend(["--format", format_str])
        return self.runner.run(command, dry_run=dry_run)

    def push(self, tag: str, *, dry_run: bool = False) -> ShellExecutionResult:
        """Push a tagged image to its registry."""
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
        """Apply a manifest file."""
        return self.runner.run(
            [*self._base(), "apply", "-f", str(manifest)], dry_run=dry_run
        )

    def delete(
        self,
        resource: str,
        name: str,
        *,
        ignore_not_found: bool = True,
        dry_run: bool = False,
    ) -> ShellExecutionResult:
        """Delete a named resource, tolerating a missing one by default."""
        command = [*self._base(), "delete", resource, name]
        if ignore_not_found:
            command.append("--ignore-not-found")
        return self.runner.run(command, dry_run=dry_run)

    def rollout_restart(
        self, resource: str, name: str, *, dry_run: bool = False
    ) -> ShellExecutionResult:
        """Restart a workload by triggering a rollout."""
        return self.runner.run(
            [*self._base(), "rollout", "restart", f"{resource}/{name}"],
            dry_run=dry_run,
        )

    def exec(
        self, pod: str, command: str, *, shell: str = "bash", dry_run: bool = False
    ) -> ShellExecutionResult:
        """Run a shell command inside a pod.

        The command string is interpreted by the shell inside the container,
        which is what makes pipes and redirection usable here. It is not passed
        through a shell on the local host: the argv list handed to the backend
        stays a list.
        """
        return self.runner.run(
            [*self._base(), "exec", pod, "--", shell, "-lc", command],
            dry_run=dry_run,
        )
