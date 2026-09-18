import os


def test_argv0(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        printf '%s\\n' "$0"
        """,
        executable="/tests/tmp/test_argv0",
    ) == "/proc/self/fd/100"


def test_argv0_relative(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        printf '%s\\n' "$0"
        """,
        executable="./test_argv0_relative",
        cwd="/tests/tmp",
    ) == "/proc/self/fd/100"


def test_argv0_uses_first_available_reserved_fd(run_program):
    try:
        saved_fd_100 = os.dup(100)
    except OSError:
        saved_fd_100 = None

    source = os.open("/dev/null", os.O_RDONLY)
    if source != 100:
        os.dup2(source, 100)
        os.close(source)
    try:
        assert run_program(
            """
            #!/usr/bin/exec-suid -- /bin/bash -p

            printf '%s\n' "$0"
            """,
            executable="/tests/tmp/test_argv0_occupied",
            pass_fds=[100],
        ) == "/proc/self/fd/101"
    finally:
        if saved_fd_100 is None:
            os.close(100)
        else:
            os.dup2(saved_fd_100, 100)
            os.close(saved_fd_100)


def test_preserve_script_path_argv0(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid --preserve-script-path -- /bin/bash -p

        printf '%s\n' "$0"
        """,
        executable="/tests/tmp/test_preserve_script_path_argv0",
    ) == "/tests/tmp/test_preserve_script_path_argv0"


def test_preserve_relative_script_path_argv0(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid --preserve-script-path -- /bin/bash -p

        printf '%s\n' "$0"
        """,
        executable="./test_preserve_relative_script_path_argv0",
        cwd="/tests/tmp",
    ) == "./test_preserve_relative_script_path_argv0"


def test_argv1(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        printf '%s\\n' "$1"
        """,
        executable="/tests/tmp/test_argv1",
        args=["/tests/tmp/test_argv1", "test"],
    ) == "test"
