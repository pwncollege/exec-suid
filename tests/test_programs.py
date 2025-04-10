import json
import pwd
import subprocess
import os


def preexec_fn(uid=1000, gid=1000, cwd="/"):
    os.setgid(gid)
    os.setuid(uid)
    os.chdir(cwd)


def test_python():
    result = json.loads(subprocess.check_output("/tests/programs/test_python", preexec_fn=preexec_fn))
    assert result["argv"] == ["/tests/programs/test_python"]
    assert result["uid"] == [1000, 0, 0]
    assert result["gid"] == [1000, 1000, 1000]


def test_python_relative():
    result = json.loads(subprocess.check_output("./test_python", preexec_fn=lambda: preexec_fn(cwd="/tests/programs")))
    assert result["argv"] == ["./test_python"]


def test_python_argv():
    result = json.loads(subprocess.check_output(["/tests/programs/test_python", "test"], preexec_fn=preexec_fn))
    assert result["argv"] == ["/tests/programs/test_python", "test"]


def test_python_env_empty():
    root_user = pwd.getpwnam("root")
    result = json.loads(subprocess.check_output("/tests/programs/test_python", env={}, preexec_fn=preexec_fn))
    assert result["env"] == {
        "PATH": os.environ.get("PATH"),
        "LOGNAME": root_user.pw_name,
        "USER": root_user.pw_name,
        "HOME": root_user.pw_dir,
        "SHELL": root_user.pw_shell,
        "MAIL": f"/var/mail/{root_user.pw_name}",
        "TERM": "unknown",
        "LANG": "C.UTF-8",
    }


def test_python_env_path():
    result = json.loads(subprocess.check_output("/tests/programs/test_python", env={"PATH": "/dangerous"}, preexec_fn=preexec_fn))
    assert result["env"]["PATH"] != "/dangerous"
    assert result["env"]["PATH"] == os.environ.get("PATH")


def test_python_env_term():
    result = json.loads(subprocess.check_output("/tests/programs/test_python", env={"TERM": "xterm"}, preexec_fn=preexec_fn))
    assert result["env"]["TERM"] == "xterm"


def test_opt_real():
    result = json.loads(subprocess.check_output("/tests/programs/test_opt_real", preexec_fn=preexec_fn))
    assert result["uid"] == [0, 0, 0]


def test_opt_environ_none():
    result = json.loads(subprocess.check_output("/tests/programs/test_opt_environ_none", preexec_fn=preexec_fn))
    result["env"].pop("LC_CTYPE")  # This environment variable may be automatically set by Python
    assert result["env"] == {}


def test_opt_environ_all():
    env = {"PATH": "/somewhere", "HELLO": "world"}
    result = json.loads(subprocess.check_output("/tests/programs/test_opt_environ_all", env=env, preexec_fn=preexec_fn))
    result["env"].pop("LC_CTYPE")  # This environment variable may be automatically set by Python
    assert result["env"] == env


def test_sh():
    result = int(subprocess.check_output("/tests/programs/test_sh", preexec_fn=preexec_fn))
    assert result == 0


def test_bash():
    result = int(subprocess.check_output("/tests/programs/test_bash", preexec_fn=preexec_fn))
    assert result == 0
