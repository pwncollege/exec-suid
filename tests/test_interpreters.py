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
    ) == "/tests/test_no_interpreter_separator"
