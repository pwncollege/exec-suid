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


def test_saved_ids_cannot_regain_root(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /usr/bin/python3 -I

        import os

        print(":".join(map(str, os.getresuid())))
        print(":".join(map(str, os.getresgid())))

        for setter in (os.seteuid, os.setegid):
            try:
                setter(0)
            except PermissionError:
                print("denied")
            else:
                print("regained")
        """,
        script_permissions=0o6755,
        script_uid=1234,
        script_gid=2345,
    ) == "1000:1234:1234\n1000:2345:2345\ndenied\ndenied"
