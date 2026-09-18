import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest


def test_execute_only_setid_script_uses_owner_permissions(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /usr/bin/python3 -I

        import os
        import stat
        import sys

        snapshot = os.stat(sys.argv[0])
        print(f"{os.geteuid()}:{os.getegid()}:{stat.S_IMODE(snapshot.st_mode):o}:{snapshot.st_uid}:{snapshot.st_gid}")
        """,
        script_permissions=0o6111,
        script_uid=1234,
        script_gid=2345,
    ) == "1234:2345:6511:1234:2345"


def test_execute_only_setgid_script(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /usr/bin/python3 -I

        import os
        import stat
        import sys

        snapshot = os.stat(sys.argv[0])
        print(f"{os.getegid()}:{stat.S_IMODE(snapshot.st_mode):o}:{snapshot.st_uid}:{snapshot.st_gid}")
        """,
        script_permissions=0o2011,
        script_uid=0,
        script_gid=1234,
    ) == "1234:2051:0:1234"


def test_interpreter_inherits_snapshot_read_only(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /usr/bin/python3 -I

        import fcntl
        import os
        import sys

        fd = int(sys.argv[0].rsplit("/", 1)[1])
        print(f"{fd}:{fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE}")
        """,
    ) == f"100:{os.O_RDONLY}"


def test_snapshot_name_resolves_relative_path(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /usr/bin/python3 -I

        import os
        import sys

        print(os.readlink(sys.argv[0]))
        """,
        executable="./snapshot_name",
        cwd="/tests/tmp",
    ) == "/memfd:/tests/tmp/snapshot_name (deleted)"


def test_snapshot_name_is_truncated(run_program):
    directory = Path("/tests/tmp") / ("d" * 200)
    directory.mkdir()
    script = directory / ("s" * 80)
    try:
        assert run_program(
            """
            #!/usr/bin/exec-suid -- /usr/bin/python3 -I

            import os
            import sys

            print(os.readlink(sys.argv[0]))
            """,
            executable=str(script),
        ) == f"/memfd:{str(script)[:249]} (deleted)"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_elevated_script_can_modify_its_snapshot(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /usr/bin/python3 -I

        import os
        import sys

        writable = os.open(sys.argv[0], os.O_WRONLY)
        os.pwrite(writable, b"#", 0)
        os.close(writable)
        print("ok")
        """,
    ) == "ok"


def test_fd_mode_allows_untrusted_parent_ownership(run_program):
    directory = Path("/tests/tmp") / f"exec_suid_untrusted_{uuid.uuid4().hex}"
    directory.mkdir(mode=0o755)
    os.chown(directory, 1000, 1000)
    try:
        assert run_program(
            """
            #!/usr/bin/exec-suid -- /bin/bash -p

            printf 'ok\n'
            """,
            executable=str(directory / "program"),
        ) == "ok"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_fd_mode_requires_caller_to_traverse_path(run_program):
    directory = Path("/tests/tmp") / f"exec_suid_private_{uuid.uuid4().hex}"
    directory.mkdir(mode=0o700)
    try:
        script = directory / "program"
        with pytest.raises(subprocess.CalledProcessError) as error:
            run_program(
                """
                #!/usr/bin/exec-suid -- /bin/bash -p

                printf 'unexpected execution\n'
                """,
                script_path=str(script),
                executable="/usr/bin/exec-suid",
                args=["/usr/bin/exec-suid", str(script)],
            )
        assert "Permission denied" in error.value.stderr
    finally:
        shutil.rmtree(directory, ignore_errors=True)
