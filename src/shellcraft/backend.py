"""Shell backends: the seam between this library and real process execution.

Every backend implements the same ``run`` contract, so orchestration code can
be exercised against a recording or scripted double instead of a real
container runtime or cluster.
"""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread
from typing import IO


@dataclass(frozen=True)
class ShellExecutionResult:
    """Outcome of a single command, whether executed or only planned.

    ``return_code`` is 0 for a dry run, so callers that branch on success do not
    need to special-case planning.
    """

    command: list[str]
    return_code: int
    stdout: str = ""
    stderr: str = ""
    dry_run: bool = False
    env: dict[str, str] = field(default_factory=dict)


OutputListener = Callable[[str, str], None]


class ShellBackend(ABC):
    """Interface every execution backend implements."""

    @abstractmethod
    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        dry_run: bool = False,
    ) -> ShellExecutionResult:
        """Run command and capture its result.

        Args:
            command: The argv list to execute.
            cwd: Working directory, or the backend's default when omitted.
            env: Variables layered on top of the inherited environment.
            dry_run: When True, skip execution and report a zero exit code.

        """
        ...


class SubprocessShell(ShellBackend):
    """Executes commands as real child processes.

    Commands are passed as an argv list and never through a shell, so shell
    metacharacters in an argument are not interpreted.
    """

    def __init__(self, output_listener: OutputListener | None = None) -> None:
        """Create a backend that forwards output to output_listener, if given."""
        self.output_listener = output_listener

    def _emit_output(self, stream: str, line: str) -> None:
        if self.output_listener is not None:
            self.output_listener(stream, line)

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        dry_run: bool = False,
    ) -> ShellExecutionResult:
        """Run command, optionally streaming its output line by line.

        With an output_listener the process is launched as a Popen and both
        pipes are drained on their own threads, so a child that writes heavily
        to stderr cannot deadlock against a full stdout buffer. Without one, a
        single blocking subprocess.run is enough.
        """
        if dry_run:
            return ShellExecutionResult(
                command=command,
                return_code=0,
                dry_run=True,
                env=env or {},
            )

        if self.output_listener is None:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env={**os.environ, **(env or {})},
                text=True,
                capture_output=True,
                check=False,
            )
            return ShellExecutionResult(
                command=command,
                return_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                dry_run=False,
                env=env or {},
            )

        process = subprocess.Popen(
            command,
            cwd=cwd,
            env={**os.environ, **(env or {})},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        def _pump(pipe: IO[str], stream: str, chunks: list[str]) -> None:
            try:
                while True:
                    line = pipe.readline()
                    if line == "":
                        break
                    chunks.append(line)
                    self._emit_output(stream, line.rstrip("\n"))
            finally:
                pipe.close()

        stdout_thread = Thread(
            target=_pump, args=(process.stdout, "stdout", stdout_chunks)
        )
        stderr_thread = Thread(
            target=_pump, args=(process.stderr, "stderr", stderr_chunks)
        )
        stdout_thread.start()
        stderr_thread.start()
        stdout_thread.join()
        stderr_thread.join()
        return_code = process.wait()

        return ShellExecutionResult(
            command=command,
            return_code=return_code,
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks),
            dry_run=False,
            env=env or {},
        )


@dataclass
class RecordingShell(ShellBackend):
    """Records the commands it is asked to run and always succeeds.

    Useful for asserting on the exact argv a caller would have executed.
    """

    commands: list[list[str]] = field(default_factory=list)

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        dry_run: bool = False,
    ) -> ShellExecutionResult:
        """Record command and report a zero exit code without executing it."""
        _ = cwd, env
        self.commands.append(command)
        return ShellExecutionResult(
            command=command,
            return_code=0,
            dry_run=dry_run,
            env=env or {},
        )


@dataclass
class ScriptedShell(ShellBackend):
    """Returns canned output per command, keyed by the argv tuple.

    Any command missing from the maps succeeds with empty output, so a test
    only has to script the calls it actually cares about.
    """

    stdout_map: dict[tuple[str, ...], str] = field(default_factory=dict)
    stderr_map: dict[tuple[str, ...], str] = field(default_factory=dict)
    return_code_map: dict[tuple[str, ...], int] = field(default_factory=dict)
    commands: list[list[str]] = field(default_factory=list)

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        dry_run: bool = False,
    ) -> ShellExecutionResult:
        """Look command up in the canned maps and return the scripted result."""
        _ = cwd
        self.commands.append(command)
        key = tuple(command)
        return ShellExecutionResult(
            command=command,
            return_code=self.return_code_map.get(key, 0),
            stdout=self.stdout_map.get(key, ""),
            stderr=self.stderr_map.get(key, ""),
            dry_run=dry_run,
            env=env or {},
        )
