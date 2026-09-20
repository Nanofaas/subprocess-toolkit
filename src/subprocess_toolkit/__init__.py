"""Shellcraft: typed subprocess orchestration for Python DevOps tooling.

Public API. Everything exported here is stable; the submodules behind it are
implementation detail.
"""

from subprocess_toolkit.backend import (
    OutputListener,
    RecordingShell,
    ScriptedShell,
    ShellBackend,
    ShellExecutionResult,
    SubprocessShell,
)
from subprocess_toolkit.fileutil import read_json_field, wrap_payload, write_json_file
from subprocess_toolkit.net import is_port_free, pick_local_port
from subprocess_toolkit.runners import (
    CommandRunner,
    ContainerRuntimeOps,
    KubectlOps,
    PlannedCommand,
)

__all__ = [
    "CommandRunner",
    "ContainerRuntimeOps",
    "KubectlOps",
    "OutputListener",
    "PlannedCommand",
    "RecordingShell",
    "ScriptedShell",
    "ShellBackend",
    "ShellExecutionResult",
    "SubprocessShell",
    "is_port_free",
    "pick_local_port",
    "read_json_field",
    "wrap_payload",
    "write_json_file",
]
