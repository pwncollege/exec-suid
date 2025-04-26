Being able to run a program suid is a powerful capability that can be used to design interesting systems.
Unfortunately, scripts, like those written in python and bash, cannot be natively run suid.
This is because their interpreters are not marked suid, and should not be.

This project aims to provide a simple interface for running scripts as suid.

For example, consider some `/flag` file, which has permissions `root:root 0400`, and we want non-root users to be able to read it if they know the password:

```python
#!/usr/bin/exec-suid -- /usr/bin/python3 -I

import sys

if input("Password: ") != "password":
    print("Incorrect password", file=sys.stderr)
    exit(1)

print(open("/flag").read())
```

Now, assuming root owns the file, root marks this script as suid (`chmod u+s`), and it will work as expected.

Without `exec-suid`, this would not work, as the python interpreter is not marked suid, and so even if the script is, it will not be able to read the file.

# Installation

> :warning: **Warning**
>
> Programs that are suid-root are inherently **dangerous**.
> This program is no exception.
> It is your responsibility to ensure that this program is secure and does not contain any vulnerabilities that will weaken your system's security.
> If you are not comfortable with this, do not install this program.

```sh
wget -O /usr/bin/exec-suid http://github.com/pwncollege/exec-suid/releases/latest/download/exec-suid && \
chmod 6755 /usr/bin/exec-suid
```

This will install the latest version of `exec-suid` to `/usr/bin/exec-suid`, and mark it as suid-root.
This program is designed to be run as root, and will not work properly if it is not.

## Docker

If you are installing this into a docker image, you can use the following Dockerfile syntax (without needing `wget` or similar dependencies):

```Dockerfile
# syntax=docker/dockerfile:1

ADD --chown=0:0 --chmod=6755 http://github.com/pwncollege/exec-suid/releases/latest/download/exec-suid /usr/bin/exec-suid

```
# Usage

The interface to `exec-suid` is the shebang line of the script you want to run suid.
Absolute paths are crucial, in a suid context, we cannot trust the PATH environment variable.

## Interpreters

Depending on the interpreter you are using, you may need to include additional arguments to the interpreter, in order to make it work properly, or to ensure that it is secure.

### Python

```
#!/usr/bin/exec-suid -- /usr/bin/python3 -I
```

> `-I`
>
> Run Python in isolated mode. This also implies -E, -P and -s options. In isolated mode sys.path contains neither the script’s directory nor the user’s site-packages directory. All PYTHON* environment variables are ignored, too. Further restrictions may be imposed to prevent the user from injecting malicious code.

See [https://docs.python.org/3/using/cmdline.html#cmdoption-I](https://docs.python.org/3/using/cmdline.html#cmdoption-I).

### Bash

```
#!/usr/bin/exec-suid -- /bin/bash -p
```

> `-p`
>
> If the shell is started with the effective user (group) id not equal to the real user (group) id, and the -p option is not supplied, no startup files are read, shell functions are not inherited from the environment, the SHELLOPTS, BASHOPTS, CDPATH, and GLOBIGNORE variables, if they appear in the environment, are ignored, and the effective user id is set to the real user id. If the -p option is supplied at invocation, the startup behavior is the same, but the effective user id is not reset.

See [https://www.man7.org/linux/man-pages/man1/bash.1.html#INVOCATION](https://www.man7.org/linux/man-pages/man1/bash.1.html#INVOCATION)

## Options

### Effective vs Real (`--real`)

By default, `exec-suid` will elevate only the effective user id (and saved user id), but not the real id.
This is the same behavior as a standard suid program.
In order to also elevate the real user id, you can use the `--real` option.

For example:
```
#!/usr/bin/exec-suid --real -- /bin/bash
```

This may be necessary if the interpreter you are using automatically sets the effective user id to the real user id, like `bash` (you can alternatively use the `-p` option to disable this behavior, see [Bash Interpreter](#Bash)).

This also has implications for the ["dumpable" process attribute](https://man7.org/linux/man-pages/man2/PR_SET_DUMPABLE.2const.html) which may be relevant in some contexts (e.g., namespaces, ptrace).

### Environment Handling (`--environ`)

By default, `exec-suid` carefully controls the environment variables passed to the invoked script to mitigate potential security risks.
However, depending on your use case, you can customize this behavior using the `--environ` option:

- **`safe` (default)**: Restricts environment variables to a safe subset:
  - Inherited from init process (pid 1): `PATH`.
  - From (new) effective user's `/etc/passwd` entry: `USER`, `HOME`, `SHELL`.
  - Preserved if set, otherwise default values: `TERM` (default: `unknown`), `LANG` (default: `C.UTF-8`).
  - Preserved if set, otherwise unset: `LANGUAGE`, `TZ`, `DISPLAY`, `LS_COLORS`, and all `LC_*` variables.
  - All other variables unset.

- **`none`**: All environment variables are unset.

- **`all`**: All environment variables are preserved. This mode is **extremely dangerous**, since it allows a malicious user to control dangerous environment variables, such as `PATH` or `LD_PRELOAD`, which can lead to arbitrary code execution, or otherwise dramatically alter the behavior of the script in unexpected ways.

For example:
```
#!/usr/bin/exec-suid --environ=none -- /usr/bin/python3 -I
```

This would run your python script with no inherited environment variables.
