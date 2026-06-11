import os
from pathlib import Path


DEFAULT_SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def test_env_path(run_program):
    result = run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        printf '%s\\n' "$PATH"
        """,
        env={"PATH": "/dangerous"},
    )
    assert result != "/dangerous"


def test_env_path_from_etc_environment(run_program):
    environ_path = Path("/etc/environment")
    backup = environ_path.read_text() if environ_path.exists() else None
    environ_path.write_text(
        """
        # comment
        export FOO=/ignored
        export PATH="/safe/from/etc:/usr/bin:/bin" # comment
        """
    )
    try:
        assert run_program(
            """
            #!/usr/bin/exec-suid -- /bin/bash -p

            printf '%s\\n' "$PATH"
            """,
            env={"PATH": "/dangerous"},
        ) == "/safe/from/etc:/usr/bin:/bin"
    finally:
        if backup is None:
            environ_path.unlink(missing_ok=True)
        else:
            environ_path.write_text(backup)


def test_env_path_default(run_program):
    environ_path = Path("/etc/environment")
    backup = environ_path.read_text() if environ_path.exists() else None
    environ_path.unlink(missing_ok=True)
    try:
        assert run_program(
            """
            #!/usr/bin/exec-suid -- /bin/bash -p

            printf '%s\\n' "$PATH"
            """,
            env={"PATH": "/dangerous"},
        ) == DEFAULT_SAFE_PATH
    finally:
        if backup is not None:
            environ_path.write_text(backup)


def test_opt_env_path(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid --env PATH=/custom/bin:/usr/bin -- /bin/bash -p

        printf '%s\\n' "$PATH"
        """,
        env={"PATH": "/dangerous"},
    ) == "/custom/bin:/usr/bin"


def test_opt_env_arbitrary_value(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid --env FOO=bar --env BAZ=quux -- /bin/bash -p

        printf '%s %s\\n' "$FOO" "$BAZ"
        """,
        env={"FOO": "/dangerous"},
    ) == "bar quux"


def test_opt_env_duplicate_value(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid --env FOO=old --env FOO=new -- /bin/bash -p

        printf '%s\\n' "$FOO"
        """
    ) == "new"


def test_env_term(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        printf '%s\\n' "$TERM"
        """,
        env={"TERM": "term-custom"},
    ) == "term-custom"


def test_env_passwd_fallback(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        printf '%s\\n%s\\n%s\\n%s\\n' "$USER" "$LOGNAME" "$HOME" "$SHELL"
        """,
        script_permissions=0o555,
        user=12345,
    ) == "#12345\n#12345\n/\n/bin/sh"


def test_env_missing_passwd_fallback(run_program):
    passwd_path = Path("/etc/passwd")
    backup_path = Path("/etc/passwd.bkup")
    passwd_path.rename(backup_path)
    try:
        assert run_program(
            """
            #!/usr/bin/exec-suid -- /bin/bash -p

            printf '%s\\n%s\\n%s\\n%s\\n' "$USER" "$LOGNAME" "$HOME" "$SHELL"
            """,
            script_permissions=0o555,
            user=12345,
        ) == "#12345\n#12345\n/\n/bin/sh"
    finally:
        backup_path.rename(passwd_path)
