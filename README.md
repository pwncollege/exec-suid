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

```sh
wget -O /usr/bin/exec-suid http://github.com/pwncollege/exec-suid/releases/latest/download/exec-suid && \
chmod 6755 /usr/bin/exec-suid
```

This will install the latest version of `exec-suid` to `/usr/bin/exec-suid`, and mark it as suid-root.
This program is designed to be run as root, and will not work properly if it is not.

> :warning: **Warning**
>
> Programs that are suid-root are inherently **dangerous**.
> This program is no exception.
> It is your responsibility to ensure that this program is secure and does not contain any vulnerabilities that will weaken your system's security.
> If you are not comfortable with this, do not install this program.

## Docker

If you are installing this into a docker image, you can use the following Dockerfile syntax (without needing `wget` or similar dependencies):

```Dockerfile
# syntax=docker/dockerfile:1

ADD --chown=0:0 --chmod=6755 http://github.com/pwncollege/exec-suid/releases/latest/download/exec-suid /usr/bin/exec-suid

```
# Usage

The interface to `exec-suid` is the shebang line of the script you want to run suid. Absolute paths are crucial, in a suid context, we cannot trust the PATH environment variable. You may need to include additional arguments to the interpreter, in order to make it work properly, or to ensure that it is secure.

## Python

```
#!/usr/bin/exec-suid -- /usr/bin/python3 -I
```

> `-I`
>
> Run Python in isolated mode. This also implies -E, -P and -s options. In isolated mode sys.path contains neither the script’s directory nor the user’s site-packages directory. All PYTHON* environment variables are ignored, too. Further restrictions may be imposed to prevent the user from injecting malicious code.

See [https://docs.python.org/3/using/cmdline.html#cmdoption-I](https://docs.python.org/3/using/cmdline. html#cmdoption-I).

## Bash

```
#!/usr/bin/exec-suid -- /bin/bash -p
```

> `-p`
>
> If the shell is started with the effective user (group) id not equal to the real user (group) id, and the -p option is not supplied, no startup files are read, shell functions are not inherited from the environment, the SHELLOPTS, BASHOPTS, CDPATH, and GLOBIGNORE variables, if they appear in the environment, are ignored, and the effective user id is set to the real user id. If the -p option is supplied at invocation, the startup behavior is the same, but the effective user id is not reset.

See [https://www.man7.org/linux/man-pages/man1/bash.1.html#INVOCATION](https://www.man7.org/linux/man-pages/man1/bash.1.html#INVOCATION).
