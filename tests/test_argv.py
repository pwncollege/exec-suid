def test_argv0(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        printf '%s\\n' "$0"
        """,
        executable="/tests/tmp/test_argv0",
    ) == "/tests/tmp/test_argv0"


def test_argv0_relative(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        printf '%s\\n' "$0"
        """,
        executable="./test_argv0_relative",
        cwd="/tests/tmp",
    ) == "./test_argv0_relative"


def test_argv1(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        printf '%s\\n' "$1"
        """,
        executable="/tests/tmp/test_argv1",
        args=["/tests/tmp/test_argv1", "test"],
    ) == "test"
