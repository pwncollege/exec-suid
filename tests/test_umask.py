def test_umask_default(run_program):
    assert int(run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        umask
        """,
        umask=0o000,
    ), 8) == 0o022
