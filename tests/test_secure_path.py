import shutil
import subprocess
import uuid
from pathlib import Path

import pytest


def test_insecure_world_writable_directory_rejected(run_program):
    directory = Path("/tmp") / f"exec_suid_insecure_{uuid.uuid4().hex}"
    directory.mkdir()
    directory.chmod(0o777)
    try:
        script = directory / "program"
        with pytest.raises(subprocess.CalledProcessError) as error:
            run_program(
                """
                #!/usr/bin/exec-suid -- /bin/bash -p

                printf 'ok\\n'
                """,
                executable=str(script),
            )
        assert "Path is insecure:" in error.value.stderr
        assert "is a world-writable non-sticky directory" in error.value.stderr
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_sticky_world_writable_directory_allowed(run_program):
    directory = Path("/tmp") / f"exec_suid_sticky_{uuid.uuid4().hex}"
    directory.mkdir()
    directory.chmod(0o1777)
    try:
        script = directory / "program"
        assert run_program(
            """
            #!/usr/bin/exec-suid -- /bin/bash -p

            printf 'ok\\n'
            """,
            executable=str(script),
        ) == "ok"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_direct_invocation_requires_script_execute_permission(run_program):
    directory = Path("/tmp") / f"exec_suid_noexec_{uuid.uuid4().hex}"
    directory.mkdir()
    try:
        script = directory / "program"
        with pytest.raises(subprocess.CalledProcessError) as error:
            run_program(
                """
                #!/usr/bin/exec-suid -- /bin/bash -p

                printf 'ok\\n'
                """,
                script_permissions=0o4700,
                script_path=str(script),
                executable="/usr/bin/exec-suid",
                args=["/usr/bin/exec-suid", str(script)],
            )
        assert "Permission denied" in error.value.stderr
    finally:
        shutil.rmtree(directory, ignore_errors=True)
