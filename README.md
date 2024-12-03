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

> **Warning**
>
> Programs that are suid-root are inherently **dangerous**.
> This program is no exception.
> It is your responsibility to ensure that this program is secure and does not contain any vulnerabilities that will weaken your system's security.
> If you are not comfortable with this, do not install this program.
