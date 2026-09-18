import subprocess
import uuid
from pathlib import Path

import pytest


def test_python(run_program):
    assert int(run_program(
        """
        #!/usr/bin/exec-suid -- /usr/bin/python3 -I

        import os

        print(os.geteuid())
        """,
    )) == 0


def test_bash(run_program):
    assert int(run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        id -u
        """,
    )) == 0


def test_sh(run_program):
    assert int(run_program(
        """
        #!/usr/bin/exec-suid -- /bin/sh -p

        id -u
        """,
    )) == 0


def test_option_like_script_path(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /usr/bin/python3 -I

        print("script")
        """,
        script_path="-cprint('injected')",
        executable="/usr/bin/exec-suid",
        args=["/usr/bin/exec-suid", "-cprint('injected')"],
        cwd="/tests",
    ) == "script"


def test_no_interpreter_separator(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid --no-interpreter-separator -- /usr/bin/python3 -I -c print(__import__('sys').argv[1])
        """,
        executable="/tests/test_no_interpreter_separator",
    ) == "/proc/self/fd/100"


def test_oversized_header_rejected(run_program):
    script = Path("/tests/tmp") / f"oversized_header_{uuid.uuid4().hex}"
    header = "#!/usr/bin/exec-suid -- /bin/sh " + "x" * (64 * 1024)

    with pytest.raises(subprocess.CalledProcessError) as error:
        run_program(
            f"{header}\nprintf 'unexpected execution\\n'\n",
            script_path=str(script),
            executable="/usr/bin/exec-suid",
            args=["/usr/bin/exec-suid", str(script)],
        )

    assert "Header exceeds the 65536-byte limit" in error.value.stderr
