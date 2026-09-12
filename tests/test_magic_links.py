import errno
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest


@pytest.mark.parametrize("target_kind", ["file", "directory"])
@pytest.mark.parametrize("spelling", ["self", "pid", "alias"])
def test_magic_link_script_path_rejected(run_program, target_kind, spelling):
    directory = Path("/tests/tmp") / f"exec_suid_magic_{uuid.uuid4().hex}"
    directory.mkdir(mode=0o755)
    script = directory / "program"
    script.touch()
    fd = os.open(script if target_kind == "file" else directory, os.O_RDONLY)
    try:
        pid = str(os.getpid()) if spelling == "pid" else "self"
        magic = Path(f"/proc/{pid}/fd/{fd}")
        if spelling == "alias":
            alias = directory / "alias"
            alias.symlink_to(magic)
            magic = alias
        executable = magic if target_kind == "file" else magic / "program"
        # Already root, with a fixed non-setid script: verify rejection of the
        # path itself without relying on target ownership or proc access denial.
        with pytest.raises(subprocess.CalledProcessError) as error:
            run_program(
                """
                #!/usr/bin/exec-suid -- /bin/sh
                printf 'unexpected execution\\n'
                """,
                script_permissions=0o755,
                script_path=str(script),
                executable="/usr/bin/exec-suid",
                args=["/usr/bin/exec-suid", str(executable)],
                pass_fds=[fd],
                user=0,
                group=0,
            )
        assert "Cannot resolve path without magic links:" in error.value.stderr
        assert f"(os error {errno.ELOOP})" in error.value.stderr
        assert error.value.stdout == ""
    finally:
        os.close(fd)
        shutil.rmtree(directory, ignore_errors=True)


def test_self_exe_rejected_before_header_parsing():
    result = subprocess.run(
        ["/usr/bin/exec-suid", "/proc/self/exe"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Cannot resolve path without magic links:" in result.stderr
    assert f"(os error {errno.ELOOP})" in result.stderr
