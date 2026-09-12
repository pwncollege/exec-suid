import errno
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest


def test_insecure_world_writable_directory_rejected(run_program):
    directory = Path("/tests/tmp") / f"exec_suid_insecure_{uuid.uuid4().hex}"
    directory.mkdir()
    directory.chmod(0o777)
    try:
        with pytest.raises(subprocess.CalledProcessError) as error:
            run_program(
                """
                #!/usr/bin/exec-suid -- /bin/bash -p

                printf 'ok\\n'
                """,
                executable=str(directory / "program"),
            )
        assert "Path is insecure:" in error.value.stderr
        assert f"{directory} is world-writable" in error.value.stderr
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_sticky_world_writable_directory_rejected(run_program):
    directory = Path("/tests/tmp") / f"exec_suid_sticky_{uuid.uuid4().hex}"
    directory.mkdir()
    directory.chmod(0o1777)
    try:
        with pytest.raises(subprocess.CalledProcessError) as error:
            run_program(
                """
                #!/usr/bin/exec-suid -- /bin/bash -p

                printf 'ok\\n'
                """,
                executable=str(directory / "program"),
            )
        assert f"{directory} is world-writable" in error.value.stderr
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture
def symlink_tree():
    directory = Path("/tests/tmp") / f"exec_suid_symlink_{uuid.uuid4().hex}"
    directory.mkdir(mode=0o755)
    (directory / "target").mkdir(mode=0o755)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


SCRIPT = """
#!/usr/bin/exec-suid -- /bin/bash -p

printf '%s\\n' "$0"
"""


@pytest.mark.parametrize("kind", ["absolute", "relative", "parent_relative", "chain", "file"])
@pytest.mark.parametrize("relative_invocation", [False, True])
def test_trusted_symlinks_preserve_script_path(run_program, symlink_tree, kind, relative_invocation):
    target = symlink_tree / "target"
    link = symlink_tree / "link"
    if kind == "file":
        link.symlink_to(target / "program")
        executable = link
    else:
        if kind == "parent_relative":
            (symlink_tree / "nested").mkdir(mode=0o755)
            link = symlink_tree / "nested" / "link"
            link.symlink_to("../target")
        elif kind == "chain":
            (symlink_tree / "intermediate").symlink_to("target")
            link.symlink_to("intermediate")
        else:
            link.symlink_to(target if kind == "absolute" else "target")
        executable = link / "program"

    executable = f"./{executable.relative_to(symlink_tree)}" if relative_invocation else str(executable)
    assert run_program(
        SCRIPT,
        script_path=str(target / "program"),
        executable=executable,
        cwd=str(symlink_tree),
    ) == executable


@pytest.mark.parametrize("component", ["link", "intermediate", "target", "script"])
def test_symlink_path_requires_root_ownership(run_program, symlink_tree, component):
    target = symlink_tree / "target"
    script = target / "program"
    link = symlink_tree / "link"
    intermediate = symlink_tree / "intermediate"
    if component == "intermediate":
        intermediate.symlink_to(target)
        link.symlink_to(intermediate)
    else:
        link.symlink_to(script if component == "script" else target)
    checked = {"link": link, "intermediate": intermediate, "target": target, "script": script}[component]
    if component == "script":
        # The shared fixture preserves an existing file's ownership when writing it.
        script.touch()
    os.chown(checked, 1000, 1000, follow_symlinks=False)
    with pytest.raises(subprocess.CalledProcessError) as error:
        run_program(
            SCRIPT,
            script_permissions=0o755,
            script_path=str(script),
            executable=str(link if component == "script" else link / "program"),
        )
    assert f"{checked} is not root-owned" in error.value.stderr


@pytest.mark.parametrize("mode", [0o777, 0o1777])
@pytest.mark.parametrize("location", ["link_parent", "target_parent", "target_ancestor", "discarded_ancestor"])
def test_symlink_path_rejects_writable_directories(run_program, symlink_tree, mode, location):
    target = symlink_tree / "target"
    unsafe = symlink_tree / "unsafe"
    unsafe.mkdir(mode=0o755)
    unsafe.chmod(mode)
    link = symlink_tree / "link"
    if location == "link_parent":
        link = unsafe / "link"
        link.symlink_to(target)
    elif location == "target_parent":
        target = unsafe
        link.symlink_to(target)
    elif location == "target_ancestor":
        target = unsafe / "nested"
        target.mkdir(mode=0o755)
        link.symlink_to(target)
    else:
        # This directory is traversed even though canonicalize() would erase it.
        link.symlink_to("unsafe/../target")
    with pytest.raises(subprocess.CalledProcessError) as error:
        run_program(SCRIPT, script_path=str(target / "program"), executable=str(link / "program"))
    assert f"{unsafe} is world-writable" in error.value.stderr


def test_symlink_to_writable_script_rejected(run_program, symlink_tree):
    script = symlink_tree / "target" / "program"
    link = symlink_tree / "link"
    link.symlink_to(script)
    with pytest.raises(subprocess.CalledProcessError) as error:
        run_program(SCRIPT, script_permissions=0o4777, script_path=str(script), executable=str(link))
    assert f"{script} is world-writable" in error.value.stderr


def test_root_delegated_group_write_allowed(run_program, symlink_tree):
    target = symlink_tree / "target"
    os.chown(target, 0, 1000)
    target.chmod(0o775)
    script = target / "program"
    script.touch()
    os.chown(script, 0, 1000)
    link = symlink_tree / "link"
    link.symlink_to(script)
    assert run_program(
        SCRIPT,
        script_permissions=0o4775,
        script_path=str(script),
        executable=str(link),
    ) == str(link)


def test_direct_symlink_invocation_requires_execute_permission(run_program, symlink_tree):
    script = symlink_tree / "target" / "program"
    link = symlink_tree / "link"
    link.symlink_to(script)
    with pytest.raises(subprocess.CalledProcessError) as error:
        run_program(
            SCRIPT,
            script_permissions=0o4700,
            script_path=str(script),
            executable="/usr/bin/exec-suid",
            args=["/usr/bin/exec-suid", str(link)],
        )
    assert "Permission denied" in error.value.stderr


def test_symlink_to_nosuid_mount_rejected(run_program, symlink_tree):
    # Docker mounts /dev as a root-owned 0755 tmpfs with nosuid. Using a
    # trusted parent ensures this reaches the mount check, not the mode check.
    directory = Path("/dev") / f"exec_suid_nosuid_{uuid.uuid4().hex}"
    directory.mkdir(mode=0o755)
    try:
        script = directory / "program"
        link = symlink_tree / "link"
        link.symlink_to(script)
        with pytest.raises(subprocess.CalledProcessError) as error:
            run_program(SCRIPT, script_path=str(script), executable=str(link))
        assert "Path is in a nosuid mount: /dev" in error.value.stderr
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@pytest.mark.parametrize("kind", ["dangling", "loop"])
def test_invalid_symlink_reports_error(run_program, symlink_tree, kind):
    link = symlink_tree / "link"
    link.symlink_to("missing" if kind == "dangling" else "link")
    with pytest.raises(subprocess.CalledProcessError) as error:
        run_program(
            SCRIPT,
            script_path=str(symlink_tree / "target" / "program"),
            executable="/usr/bin/exec-suid",
            args=["/usr/bin/exec-suid", str(link)],
        )
    expected_errno = errno.ENOENT if kind == "dangling" else errno.ELOOP
    assert f"(os error {expected_errno})" in error.value.stderr


def test_world_writable_script_rejected(run_program):
    with pytest.raises(subprocess.CalledProcessError) as error:
        run_program(
            """
            #!/usr/bin/exec-suid -- /bin/bash -p

            printf 'ok\\n'
            """,
            script_permissions=0o4777,
        )
    assert "is world-writable" in error.value.stderr


def test_direct_invocation_requires_script_execute_permission(run_program):
    directory = Path("/tests/tmp") / f"exec_suid_noexec_{uuid.uuid4().hex}"
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
