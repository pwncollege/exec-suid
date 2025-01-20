import json
import subprocess
import os


def preexec_fn(uid=1000, gid=1000, cwd="/"):
    os.setgid(gid)
    os.setuid(uid)
    os.chdir(cwd)


def test_python():
    result = json.loads(subprocess.check_output("/tests/programs/test_python", preexec_fn=preexec_fn))
    result["env"].pop("LC_CTYPE")  # This environment variable may be automatically set by Python"
    assert result == dict(argv=["/tests/programs/test_python"],
                          env={},
                          uid=[1000, 0, 0],
                          gid=[1000, 1000, 1000])


def test_python_relative():
    result = json.loads(subprocess.check_output("./test_python", preexec_fn=lambda: preexec_fn(cwd="/tests/programs")))
    assert result["argv"] == ["./test_python"]


def test_python_argv():
    result = json.loads(subprocess.check_output(["/tests/programs/test_python", "test"], preexec_fn=preexec_fn))
    assert result["argv"] == ["/tests/programs/test_python_argv", "test"]


def test_sh():
    result = int(subprocess.check_output("/tests/programs/test_sh", preexec_fn=preexec_fn))
    assert result == 0


def test_bash():
    result = int(subprocess.check_output("/tests/programs/test_bash", preexec_fn=preexec_fn))
    assert result == 0


def test_opt_real():
    result = json.loads(subprocess.check_output("/tests/programs/test_opt_real", preexec_fn=preexec_fn))
    assert result["uid"] == [0, 0, 0]
