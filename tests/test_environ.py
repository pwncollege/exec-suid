import base64
import os
import subprocess
from pathlib import Path

import pytest


DEFAULT_SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
PASSTHROUGH_KEYS = (
    "TERM", "LANG", "LANGUAGE", "TZ", "DISPLAY", "LS_COLORS", "LC_ALL",
    "LC_CTYPE", "LC_NUMERIC", "LC_TIME", "LC_COLLATE", "LC_MONETARY",
    "LC_MESSAGES",
)
ENV_DEFAULTS = {"TERM": "unknown", "LANG": "C.UTF-8"}


@pytest.fixture(params=["", "--real"])
def env_value(run_program, request):
    def _read(key, value=None):
        result = run_program(
            f"""
            #!/usr/bin/exec-suid {request.param} -- /bin/bash -p

            printf '%s' "${{{key}-unset}}" | /usr/bin/base64 -w 0
            """,
            env={} if value is None else {key: value},
            errors="surrogateescape",
        )
        return base64.b64decode(result)

    return _read


@pytest.mark.parametrize("key", PASSTHROUGH_KEYS)
def test_env_passthrough(env_value, key):
    assert env_value(key, "custom") == b"custom"


@pytest.mark.parametrize("value", [b"", b"x" * 8192, ("é" * 4096).encode(), b"custom\xff"])
def test_env_byte_values(env_value, value):
    assert env_value("LANGUAGE", value) == value


@pytest.mark.parametrize("key,value", [
    ("TERM", "../xterm"),
    ("LANG", "/tmp/locale"),
    ("LANGUAGE", "../../../../tmp/x"),
    ("LANGUAGE", ".."),
    ("LANGUAGE", "a..b"),
    ("LC_MESSAGES", "..@custom"),
    ("LC_ALL", "en_US/UTF-8"),
    ("LANGUAGE", "a\nb"),
    ("DISPLAY", "a\x7fb"),
    ("LS_COLORS", "\x1b[31m"),
    ("LANGUAGE", "x" * 8193),
    ("LANGUAGE", "é" * 4096 + "x"),
    ("DISPLAY", "x" * 8193),
    ("LS_COLORS", "x" * 8193),
])
def test_env_rejected_values(env_value, key, value):
    assert env_value(key, value) == ENV_DEFAULTS.get(key, "unset").encode()


@pytest.mark.parametrize("key,value", [
    ("DISPLAY", "tcp/host:0"),
    ("DISPLAY", "/tmp/../display:0"),
    ("LS_COLORS", "di=01;34:*.a..b=01;31:*/=01;34"),
    ("LS_COLORS", "x" * 8192),
    ("TZ", "America/New_York"),
    ("TZ", ":America/New_York"),
    ("TZ", "EST5EDT,M3.2.0/2,M11.1.0/2"),
    ("TZ", "/etc/localtime"),
    ("TZ", ":/etc/localtime"),
])
def test_env_special_values(env_value, key, value):
    assert env_value(key, value) == value.encode()


@pytest.mark.parametrize("value", [
    "/tmp/x", ":/tmp/x", "/etc/localtime/", "/usr/share/zoneinfo/UTC", ":../tmp/x",
])
def test_env_tz_unsafe(env_value, value):
    assert env_value("TZ", value) == b"unset"


@pytest.mark.parametrize("key", [
    "LC_", "LC_UNKNOWN", "LC_MESSAGES_EXTRA", "LC_PAPER",
    "TERMINFO", "TERMINFO_DIRS", "TERMCAP", "TZDIR",
])
def test_env_unlisted_keys(env_value, key):
    assert env_value(key, "custom") == b"unset"


@pytest.mark.parametrize("key,expected", ENV_DEFAULTS.items())
def test_env_defaults(env_value, key, expected):
    assert env_value(key) == expected.encode()


@pytest.mark.parametrize("real", ["", "--real"])
def test_env_non_utf8_key_ignored(run_program, real):
    assert run_program(
        f"""
        #!/usr/bin/exec-suid {real} -- /bin/bash -p

        printf 'ok'
        """,
        env={b"LC_\xff": b"custom"},
    ) == "ok"


@pytest.mark.parametrize("real", ["", "--real"])
def test_opt_env_overrides_filter(run_program, real):
    assert run_program(
        f"""
        #!/usr/bin/exec-suid {real} --env LANGUAGE=/trusted/catalog -- /bin/bash -p

        printf '%s\\n' "$LANGUAGE"
        """,
        env={"LANGUAGE": "../../../../tmp/x"},
    ) == "/trusted/catalog"


def test_deprecated_environ_option_is_rejected(run_program):
    with pytest.raises(subprocess.CalledProcessError) as error:
        run_program(
            """
            #!/usr/bin/exec-suid --environ all -- /bin/bash -p

            printf 'unexpected execution\n'
            """
        )
    assert "Unrecognized option: 'environ'" in error.value.stderr


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
