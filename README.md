# shellcraft

Generic subprocess orchestration toolkit for Python DevOps tooling.

`shellcraft` separates *deciding what to run* from *running it*. Commands are
built as typed argv lists by small dataclasses, execution goes through a
swappable backend, and every operation supports a dry run — so the same code
that drives a real cluster in production can be asserted against in a test
without mocking `subprocess` by hand.

It is stdlib-only. There are no runtime dependencies.

## Install

```bash
uv add shellcraft
# or
pip install shellcraft
```

## Concepts

Three pieces, and they compose:

- **`ShellBackend`** — executes a command and returns a `ShellExecutionResult`.
  `SubprocessShell` runs real processes; `RecordingShell` and `ScriptedShell`
  are test doubles.
- **`CommandRunner`** — binds a backend to a working-directory root.
- **`ContainerRuntimeOps` / `KubectlOps`** — build the command lines for docker,
  podman, nerdctl or kubectl and hand them to a runner.

## Quick start

```python
from shellcraft import CommandRunner, ContainerRuntimeOps, KubectlOps

runner = CommandRunner()  # SubprocessShell by default
docker = ContainerRuntimeOps(runner, runtime="podman")

docker.build("myapp:latest", context=".", build_args={"PY": "3.12"})
docker.run_container(
    "myapp:latest",
    name="myapp",
    detach=True,
    ports={8080: 80},
    env={"MODE": "prod"},
)
docker.push("registry.example.com/myapp:latest")

kubectl = KubectlOps(runner, namespace="staging")
kubectl.apply("deploy.yaml")
kubectl.rollout_restart("deployment", "myapp")
kubectl.exec("myapp-7f9c", "curl -s localhost:80/health")
```

### Dry runs

Every operation takes `dry_run=True`. Nothing is executed, and the returned
result carries `return_code == 0` plus a `dry_run` flag, so success checks keep
working while you render a plan:

```python
result = docker.run_container("myapp:latest", dry_run=True)
print(result.command)  # ['podman', 'run', 'myapp:latest']
print(result.dry_run)  # True
```

### Testing without a cluster

`RecordingShell` captures the exact argv a caller produced:

```python
from shellcraft import CommandRunner, KubectlOps, RecordingShell

shell = RecordingShell()
kubectl = KubectlOps(CommandRunner(shell=shell), namespace="prod")

kubectl.delete("deployment", "myapp")

assert shell.commands == [
    ["kubectl", "-n", "prod", "delete", "deployment", "myapp", "--ignore-not-found"]
]
```

`ScriptedShell` goes further and returns canned stdout, stderr and exit codes
per command, for exercising the code that *reacts* to a result.

### Streaming output

Pass an `output_listener` to `SubprocessShell` to receive each line as it is
produced. Both pipes are drained on their own threads, so a child that writes
heavily to stderr cannot deadlock against a full stdout buffer:

```python
from shellcraft import CommandRunner, SubprocessShell

shell = SubprocessShell(output_listener=lambda stream, line: print(stream, line))
CommandRunner(shell=shell).run(["make", "all"])
```

### Ports

`is_port_free` and `pick_local_port` cover the common "give me a port that is
not taken" step, checking IPv4 and, where the host supports it, IPv6:

```python
from shellcraft import pick_local_port

port = pick_local_port(preferred=8080, blocked={9090})
```

### JSON helpers

`read_json_field`, `write_json_file` and `wrap_payload` handle the small
read-a-field / write-a-payload work that shows up around CLI tooling.

## Development

```bash
uv sync --all-extras
uv run pre-commit install
```

The same hooks run in CI, so a green local run means a green pipeline:

```bash
uv run pre-commit run --all-files
```

Individual commands, if you want them:

| | |
| --- | --- |
| Lint | `uv run ruff check .` (add `--fix`) |
| Format | `uv run ruff format .` |
| Types | `uv run mypy` (strict) |
| Tests | `uv run pytest` |
| Coverage | `uv run pytest --cov` |
| Security | `uv run bandit -c pyproject.toml -r src` |

Ruff is pinned exactly in `pyproject.toml` and mirrored by the
`ruff-pre-commit` revision in `.pre-commit-config.yaml`. Bump both together, or
the hook and a local `ruff check` will disagree.

## Design notes

Commands are always built as argv lists and never passed through a shell, so
shell metacharacters in an argument are not interpreted. The one place a shell
is involved is `KubectlOps.exec`, where the command string is interpreted by
the shell **inside the pod** — that is what makes pipes and redirection usable
there, and it is `kubectl exec` semantics rather than a local `shell=True`.

## License

Apache License 2.0. See [LICENSE](LICENSE).
