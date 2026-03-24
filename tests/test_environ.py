import os
from pathlib import Path


def test_env_path(run_program):
    result = run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        printf '%s\\n' "$PATH"
        """,
        env={"PATH": "/dangerous"},
    )
    assert result != "/dangerous"
    assert result == os.environ.get("PATH")


def test_env_term(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid -- /bin/bash -p

        printf '%s\\n' "$TERM"
        """,
        env={"TERM": "term-custom"},
    ) == "term-custom"


def test_opt_environ_none(run_program):
    result = run_program(
        """
        #!/usr/bin/exec-suid --environ=none -- /bin/bash -p

        printf '%s\\n' "$TERM"
        """,
        env={"TERM": "term-custom"},
    )
    assert result != "term-custom"


def test_opt_environ_all(run_program):
    assert run_program(
        """
        #!/usr/bin/exec-suid --environ=all -- /bin/bash -p

        printf '%s\\n' "$PATH"
        """,
        env={"PATH": "/dangerous"},
    ) == "/dangerous"


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
