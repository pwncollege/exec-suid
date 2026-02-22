def test_gid(run_program):
    assert int(run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        id -g
        """,
    )) == 1000


def test_real_uid(run_program):
    assert int(run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        id -ru
        """,
    )) == 1000


def test_opt_real(run_program):
    assert int(run_program(
        """
        #!/usr/bin/exec-suid --real -- /bin/bash -p

        id -ru
        """,
    )) == 0
