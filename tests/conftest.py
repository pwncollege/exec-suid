import subprocess
import textwrap
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def run_program():
    def _run(script, script_permissions=0o4755, **popen_kwargs):
        if popen_kwargs.get("executable") is not None:
            executable_path = str(popen_kwargs["executable"])
        else:
            executable_path = str(Path("/tmp") / f"program_{uuid.uuid4().hex}")

        script_path = Path(executable_path)
        if not script_path.is_absolute():
            script_path = Path(popen_kwargs.get("cwd") or Path.cwd()) / script_path

        script_path.write_text(textwrap.dedent(script).lstrip())
        script_path.chmod(script_permissions)

        popen_kwargs["stdout"] = subprocess.PIPE
        popen_kwargs["text"] = True
        popen_kwargs.setdefault("executable", executable_path)
        popen_kwargs.setdefault("args", [executable_path])
        popen_kwargs.setdefault("user", 1000)
        popen_kwargs.setdefault("group", 1000)
        try:
            process = subprocess.Popen(**popen_kwargs)
            stdout, _ = process.communicate()
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, popen_kwargs["args"], output=stdout)
        finally:
            script_path.unlink(missing_ok=True)

        return stdout.strip()

    return _run
