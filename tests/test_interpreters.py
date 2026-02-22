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
