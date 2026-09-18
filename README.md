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

## Script paths

By default, `exec-suid` resolves the script path once using the caller's filesystem credentials and pins the resulting file descriptor.
The caller must be able to traverse the supplied path and execute the resulting regular file.
The file must not be on a `nosuid` or `noexec` mount.

The pinned script is copied into an anonymous memory-backed file, and the interpreter receives that snapshot through the first available file descriptor at or above 100 (for example, `/proc/self/fd/100`).
Only a read-only descriptor is inherited by the interpreter.
The memfd's diagnostic name is the resolved source path, truncated to Linux's 249-byte limit.
The snapshot retains the source owner, group, and permission bits; read permission is added to the permission class selected by the final credentials.
FD-backed scripts are limited to 64 MiB.

Because the interpreter never reopens the supplied path, parent directories and symlinks do not need trusted ownership and may be writable.
Renaming or replacing the path after it has been opened cannot change the executed snapshot.

The interpreter-visible script name is `/proc/self/fd/N`, where `N` is the first available descriptor at or above 100, not the supplied path.
This changes values such as Bash's `$0`, Python's `sys.argv[0]` and `__file__`, and paths used for relative imports or resources.
Use `--preserve-script-path` when the script requires its original name.

### Preserving the script path

`--preserve-script-path` passes the supplied path to the interpreter instead of creating a snapshot:

```
#!/usr/bin/exec-suid --preserve-script-path -- /usr/bin/python3 -I
```

This mode requires every component of the script path, including symlinks and their targets, to be owned by root:root.
Non-symlink files and directories must not be other-writable, even with the sticky bit.
Group write is permitted because every accepted component belongs to the trusted root group (GID 0).
Ordinary symlink mode bits are ignored, but ownership and all original and target components are checked.
Kernel magic links such as `/proc/self/fd/N` and `/proc/PID/exe` are rejected, including through aliases.

Path-preserving validation requires Linux 5.6+ and permission to call `openat2` with `RESOLVE_NO_MAGICLINKS`; execution fails if that check is unavailable or blocked.

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

### PHP

PHP expects the script path to immediately follow its `-f` option, so the implicit interpreter separator must be disabled:

```
#!/usr/bin/exec-suid --no-interpreter-separator -- /usr/bin/php -f
```

See [https://www.php.net/manual/en/features.commandline.options.php](https://www.php.net/manual/en/features.commandline.options.php).

## Options

### Script Path (`--preserve-script-path`)

By default, the interpreter reads an FD-backed snapshot and sees `/proc/self/fd/N` as the script name, with `N` allocated from 100 upward.
Use `--preserve-script-path` to pass the original path to the interpreter for scripts that depend on `$0`, `sys.argv[0]`, `__file__`, or path-relative resources.
The original path is accepted only when it satisfies the trusted path requirements described above.

### Interpreter Separator (`--no-interpreter-separator`)

By default, `exec-suid` inserts `--` between the configured interpreter arguments and the script path. This prevents an option-like script path from being interpreted as an interpreter argument.

Some interpreters instead require the script path to immediately follow an option. Use `--no-interpreter-separator` for these command forms so that `exec-suid` does not insert `--` before the script path. See the [PHP interpreter](#php) example.

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

### Environment Handling (`--env`)

By default, `exec-suid` carefully controls the environment variables passed to the invoked script to mitigate potential security risks.

The default environment is restricted to a safe subset:

- `PATH` is read from `/etc/environment`. If `/etc/environment` does not set `PATH`, `exec-suid` uses `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`.
- From the new effective user's `/etc/passwd` entry: `USER`, `LOGNAME`, `HOME`, and `SHELL`.
- Preserved from the caller if set, otherwise default values: `TERM` (default: `unknown`), `LANG` (default: `C.UTF-8`).
- Preserved from the caller if set, otherwise unset: `LANGUAGE`, `TZ`, `DISPLAY`, `LS_COLORS`, and all `LC_*` variables.
- All other variables unset.

Set additional environment variables in the shebang with repeated `--env KEY=VALUE` options; these override the default safe environment.

For example:
```
#!/usr/bin/exec-suid --env PATH=/usr/bin:/bin --env APP_MODE=production -- /usr/bin/python3 -I
```
