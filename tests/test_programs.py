import subprocess
import os

import pytest
import yaml


test_configs = yaml.safe_load(open("/tests/test_programs.yml"))


@pytest.mark.parametrize("config", test_configs, ids=[test_config["name"] for test_config in test_configs])
def test_program(config):
    name = config["name"]

    config.setdefault("path", f"/tests/programs/{name}")

    config.setdefault("permissions", {})
    config["permissions"].setdefault("user", 1000)
    config["permissions"].setdefault("group", 1000)
    config["permissions"].setdefault("mode", 0o755)

    config.setdefault("run_as", {})
    config["run_as"].setdefault("user", 1000)
    config["run_as"].setdefault("group", 1000)

    os.chown(config["path"], config["permissions"]["user"], config["permissions"]["group"])
    os.chmod(config["path"], config["permissions"]["mode"])

    def preexec_fn():
        os.setgid(config["run_as"]["group"])
        os.setuid(config["run_as"]["user"])

    subprocess.run(["ls", "-l", config["path"]])

    subprocess.run(config["path"], preexec_fn=preexec_fn, check=True)
