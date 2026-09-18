use getopts::Options;
use nix::fcntl::{self, FcntlArg, OFlag, OpenHow, ResolveFlag, AT_FDCWD};
use nix::sys::memfd::{memfd_create, MFdFlags};
use nix::sys::resource::{self, Resource};
use nix::sys::stat::{self, Mode, SFlag};
use nix::sys::statvfs::{self, FsFlags};
use nix::unistd::{self, AccessFlags, Gid, Uid, User};
use std::collections::BTreeMap;
use std::ffi::CString;
use std::fs::{self, File};
use std::io::{self, BufRead, Read, Seek};
use std::os::{
    fd::{AsRawFd, RawFd},
    unix::ffi::OsStrExt,
};
use std::path::{Path, PathBuf};
use std::{env, process};

const DEFAULT_PATH: &str = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin";
const MAX_HEADER_SIZE: usize = 64 * 1024;
const MAX_SCRIPT_SIZE: u64 = 64 * 1024 * 1024;
const MEMFD_NAME_MAX: usize = nix::libc::NAME_MAX as usize - b"memfd:".len();
const SCRIPT_FD_MIN: RawFd = 100;

struct ScriptFd(RawFd);

impl AsRawFd for ScriptFd {
    fn as_raw_fd(&self) -> RawFd {
        self.0
    }
}

impl Drop for ScriptFd {
    fn drop(&mut self) {
        let _ = unistd::close(self.0);
    }
}

struct Credentials {
    ruid: Uid,
    euid: Uid,
    rgid: Gid,
    egid: Gid,
}

impl Credentials {
    fn from_script(source_stat: &stat::FileStat, set_real_ids: bool) -> Self {
        let mode = Mode::from_bits_truncate(source_stat.st_mode);
        let caller_uid = Uid::current();
        let caller_gid = Gid::current();

        let euid = if mode.contains(Mode::S_ISUID) {
            Uid::from_raw(source_stat.st_uid)
        } else {
            caller_uid
        };
        let egid = if mode.contains(Mode::S_ISGID) {
            Gid::from_raw(source_stat.st_gid)
        } else {
            caller_gid
        };
        let (ruid, rgid) = if set_real_ids {
            (euid, egid)
        } else {
            (caller_uid, caller_gid)
        };

        Self {
            ruid,
            euid,
            rgid,
            egid,
        }
    }
}

fn fail(path: &Path, err: impl std::fmt::Display) -> ! {
    eprintln!("{}: {}", path.display(), err);
    process::exit(1);
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() <= 1 {
        eprintln!("Usage: {} [path]", args[0]);
        process::exit(1);
    }

    let (path, user_args) = if args.len() == 2 {
        (Path::new(&args[1]), &args[2..])
    } else {
        (Path::new(&args[2]), &args[3..])
    };

    let (mut source, source_stat) = open_script(path).unwrap_or_else(|err| fail(path, err));
    let (exec_suid_argv, mut interpreter_argv) =
        parse_header(&mut source).unwrap_or_else(|err| fail(path, err));
    if exec_suid_argv[0] != args[0] {
        fail(path, "Executable path does not match");
    }

    let options = parse_options(&exec_suid_argv[1..]).unwrap_or_else(|err| fail(path, err));

    let Credentials {
        ruid,
        euid,
        rgid,
        egid,
    } = Credentials::from_script(&source_stat, options.opt_present("real"));

    let script_fd = if options.opt_present("preserve-script-path") {
        validate_secure_path(path).unwrap_or_else(|err| fail(path, err));
        None
    } else {
        Some(
            snapshot_script(
                &mut source,
                &source_stat,
                &exec_suid_argv,
                &interpreter_argv,
                euid,
                egid,
            )
            .unwrap_or_else(|err| fail(path, err)),
        )
    };
    let script_path_arg = script_fd.as_ref().map_or_else(
        || path.to_str().unwrap().to_owned(),
        |fd| format!("/proc/self/fd/{}", fd.as_raw_fd()),
    );
    drop(source);

    if !options.opt_present("no-interpreter-separator") {
        interpreter_argv.push("--".to_string());
    }
    interpreter_argv.push(script_path_arg);
    interpreter_argv.extend_from_slice(user_args);

    let env = build_safe_env(euid, &options.opt_strs("env")).unwrap_or_else(|err| fail(path, err));

    resource::setrlimit(Resource::RLIMIT_CORE, 0, 0).unwrap_or_else(|err| fail(path, err));

    unistd::setresgid(rgid, egid, Gid::from_raw(u32::MAX)).unwrap_or_else(|err| fail(path, err));
    unistd::setresuid(ruid, euid, Uid::from_raw(u32::MAX)).unwrap_or_else(|err| fail(path, err));

    stat::umask(Mode::from_bits_truncate(0o022));

    let executable = CString::new(interpreter_argv[0].as_str()).unwrap();
    let argv = interpreter_argv
        .iter()
        .map(|arg| CString::new(arg.as_str()).unwrap())
        .collect::<Vec<_>>();

    unistd::execve(&executable, &argv, &env).unwrap_or_else(|err| fail(path, err));
}

fn parse_options(args: &[String]) -> Result<getopts::Matches, getopts::Fail> {
    let mut parser = Options::new();
    parser.optflag("", "real", "Set real user and group IDs");
    parser.optmulti("", "env", "Set an environment variable", "KEY=VALUE");
    parser.optflag(
        "",
        "no-interpreter-separator",
        "Do not add a script separator",
    );
    parser.optflag(
        "",
        "preserve-script-path",
        "Pass the original trusted script path",
    );
    parser.parse(args)
}

fn parse_header(file: &mut File) -> io::Result<(Vec<String>, Vec<String>)> {
    file.rewind()?;
    let mut first_line = String::new();
    let mut reader = io::BufReader::new(file.take(MAX_HEADER_SIZE as u64 + 1));
    let header_size = reader.read_line(&mut first_line)?;
    if header_size > MAX_HEADER_SIZE {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!("Header exceeds the {MAX_HEADER_SIZE}-byte limit"),
        ));
    }
    if header_size == 0 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Script is empty",
        ));
    }
    let first_line = first_line.lines().next().unwrap_or_default();

    let header = first_line
        .strip_prefix("#!")
        .ok_or_else(|| io::Error::other("Header does not start with #!"))?;
    let tokens: Vec<String> = header.split_whitespace().map(String::from).collect();
    let split_index = tokens
        .iter()
        .position(|token| token == "--")
        .ok_or_else(|| io::Error::other("Header does not contain a -- separator"))?;

    if split_index == 0 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Header does not name exec-suid",
        ));
    }
    if split_index + 1 == tokens.len() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Header does not name an interpreter",
        ));
    }

    Ok((
        tokens[..split_index].to_vec(),
        tokens[split_index + 1..].to_vec(),
    ))
}

fn nix_error(err: nix::errno::Errno) -> io::Error {
    io::Error::from_raw_os_error(err as i32)
}

fn io_context(context: &str, err: io::Error) -> io::Error {
    io::Error::new(err.kind(), format!("{context}: {err}"))
}

fn open_script(path: &Path) -> io::Result<(File, stat::FileStat)> {
    // Pin with the caller's filesystem credentials without opening an unchecked
    // FIFO or device.
    let caller_uid = Uid::current();
    let caller_gid = Gid::current();
    let old_fsgid = unistd::setfsgid(caller_gid);
    let old_fsuid = unistd::setfsuid(caller_uid);
    let opened = fcntl::open(path, OFlag::O_PATH | OFlag::O_CLOEXEC, Mode::empty());
    unistd::setfsuid(old_fsuid);
    unistd::setfsgid(old_fsgid);

    let pinned = opened
        .map_err(nix_error)
        .map_err(|err| io_context("Cannot resolve script path", err))?;
    let source_stat = stat::fstat(&pinned).map_err(nix_error)?;
    if SFlag::from_bits_truncate(source_stat.st_mode) != SFlag::S_IFREG {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "Script is not a regular file",
        ));
    }

    let pinned_path = format!("/proc/self/fd/{}", pinned.as_raw_fd());
    unistd::access(pinned_path.as_str(), AccessFlags::X_OK).map_err(nix_error)?;

    let source_fd = fcntl::open(
        pinned_path.as_str(),
        OFlag::O_RDONLY | OFlag::O_CLOEXEC,
        Mode::empty(),
    )
    .map_err(nix_error)
    .map_err(|err| io_context("Cannot open pinned script for reading", err))?;
    let source = File::from(source_fd);
    let mount_flags = statvfs::fstatvfs(&source).map_err(nix_error)?.flags();
    if mount_flags.contains(FsFlags::ST_NOSUID) {
        return Err(io::Error::other("Path is in a nosuid mount"));
    }
    if mount_flags.contains(FsFlags::ST_NOEXEC) {
        return Err(io::Error::other("Path is in a noexec mount"));
    }

    Ok((source, source_stat))
}

fn snapshot_script(
    source: &mut File,
    source_stat: &stat::FileStat,
    expected_exec_suid_argv: &[String],
    expected_interpreter_argv: &[String],
    euid: Uid,
    egid: Gid,
) -> io::Result<ScriptFd> {
    source.rewind()?;

    let source_path = fs::read_link(format!("/proc/self/fd/{}", source.as_raw_fd()))?;
    let source_path = source_path.as_os_str().as_bytes();
    let memfd_name = CString::new(&source_path[..source_path.len().min(MEMFD_NAME_MAX)]).unwrap();
    let memfd = memfd_create(memfd_name.as_c_str(), MFdFlags::MFD_CLOEXEC).map_err(nix_error)?;
    let mut snapshot = File::from(memfd);

    let snapshot_size = io::copy(&mut source.take(MAX_SCRIPT_SIZE + 1), &mut snapshot)?;
    if snapshot_size > MAX_SCRIPT_SIZE {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!("Script exceeds the {MAX_SCRIPT_SIZE}-byte snapshot limit"),
        ));
    }

    let source_after_copy = stat::fstat(&*source).map_err(nix_error)?;
    if source_stat.st_mode != source_after_copy.st_mode
        || source_stat.st_uid != source_after_copy.st_uid
        || source_stat.st_gid != source_after_copy.st_gid
        || source_stat.st_size != source_after_copy.st_size
    {
        return Err(io::Error::other(
            "Script changed while it was being snapshotted",
        ));
    }

    let (snapshot_exec_suid_argv, snapshot_interpreter_argv) = parse_header(&mut snapshot)?;
    if snapshot_exec_suid_argv != expected_exec_suid_argv
        || snapshot_interpreter_argv != expected_interpreter_argv
    {
        return Err(io::Error::other(
            "Script header changed while it was being snapshotted",
        ));
    }

    unistd::fchown(
        &snapshot,
        Some(Uid::from_raw(source_stat.st_uid)),
        Some(Gid::from_raw(source_stat.st_gid)),
    )
    .map_err(nix_error)?;
    stat::fchmod(&snapshot, snapshot_mode(source_stat, euid, egid)?).map_err(nix_error)?;

    let snapshot_path = format!("/proc/self/fd/{}", snapshot.as_raw_fd());
    let readonly_fd = fcntl::open(
        snapshot_path.as_str(),
        OFlag::O_RDONLY | OFlag::O_CLOEXEC,
        Mode::empty(),
    )
    .map_err(nix_error)
    .map_err(|err| io_context("Cannot reopen script snapshot read-only", err))?;
    let readonly = File::from(readonly_fd);
    drop(snapshot);

    let script_fd = fcntl::fcntl(&readonly, FcntlArg::F_DUPFD(SCRIPT_FD_MIN)).map_err(nix_error)?;

    Ok(ScriptFd(script_fd))
}

fn snapshot_mode(source_stat: &stat::FileStat, euid: Uid, egid: Gid) -> io::Result<Mode> {
    let mut mode = source_stat.st_mode & 0o7777;
    let source_uid = Uid::from_raw(source_stat.st_uid);
    let source_gid = Gid::from_raw(source_stat.st_gid);

    // Make the permission class selected by the final credentials readable.
    if euid == source_uid {
        mode |= 0o400;
    } else {
        let supplementary_groups = unistd::getgroups().map_err(nix_error)?;
        if egid == source_gid || supplementary_groups.contains(&source_gid) {
            mode |= 0o040;
        } else {
            mode |= 0o004;
        }
    }

    Ok(Mode::from_bits_truncate(mode))
}

fn validate_secure_path(path: &Path) -> io::Result<()> {
    let full_path = if path.is_relative() {
        env::current_dir()?.join(path)
    } else {
        path.to_path_buf()
    };
    validate_path_components(&full_path, &mut 0)?;
    validate_no_magic_links(path)
}

fn validate_no_magic_links(path: &Path) -> io::Result<()> {
    // Nondumpable processes can expose root-owned proc links to caller-controlled
    // targets. Follow the final component so it is rejected too.
    let how = OpenHow::new()
        .flags(OFlag::O_PATH | OFlag::O_CLOEXEC)
        .resolve(ResolveFlag::RESOLVE_NO_MAGICLINKS);

    fcntl::openat2(AT_FDCWD, path, how)
        .map_err(nix_error)
        .map_err(|err| io_context("Cannot resolve path without magic links", err))?;
    Ok(())
}

fn validate_path_components(path: &Path, symlinks: &mut usize) -> io::Result<PathBuf> {
    let mut current_path = PathBuf::new();
    for component in path.components() {
        current_path.push(component);
        let component_stat = stat::lstat(&current_path)?;
        if component_stat.st_uid != 0 || component_stat.st_gid != 0 {
            return Err(io::Error::other(format!(
                "Path is insecure: {} is not owned by root:root",
                current_path.display()
            )));
        }

        if SFlag::from_bits_truncate(component_stat.st_mode) == SFlag::S_IFLNK {
            // Resolve symlinks here without skipping their checked ancestors.
            *symlinks += 1;
            if *symlinks > 40 {
                return Err(io::Error::from_raw_os_error(
                    nix::errno::Errno::ELOOP as i32,
                ));
            }
            let target = fs::read_link(&current_path)?;
            let target = current_path.parent().unwrap().join(target);
            current_path = validate_path_components(&target, symlinks)?;
            continue;
        }

        if Mode::from_bits_truncate(component_stat.st_mode).contains(Mode::S_IWOTH) {
            return Err(io::Error::other(format!(
                "Path is insecure: {} is world-writable",
                current_path.display()
            )));
        }
    }

    Ok(current_path)
}

fn build_safe_env(euid: Uid, env_overrides: &[String]) -> Result<Vec<CString>, String> {
    let (username, home, shell) = match User::from_uid(euid).ok().flatten() {
        Some(user) => (
            user.name,
            user.dir.display().to_string(),
            user.shell.display().to_string(),
        ),
        None => (format!("#{}", euid.as_raw()), "/".into(), "/bin/sh".into()),
    };

    let mut env_vars = BTreeMap::from([
        ("USER".to_string(), username.clone()),
        ("LOGNAME".to_string(), username),
        ("HOME".to_string(), home),
        ("SHELL".to_string(), shell),
    ]);

    for (key, default) in [("TERM", "unknown"), ("LANG", "C.UTF-8")] {
        env_vars.insert(key.into(), env::var(key).unwrap_or_else(|_| default.into()));
    }

    env_vars.extend(env::vars().filter(|(key, _)| {
        matches!(key.as_str(), "LANGUAGE" | "TZ" | "DISPLAY" | "LS_COLORS")
            || key.starts_with("LC_")
    }));

    for env_override in env_overrides {
        let (key, value) = env_override
            .split_once('=')
            .ok_or_else(|| format!("--env requires KEY=VALUE: {env_override}"))?;
        if key.is_empty() || key.contains('\0') {
            return Err(format!("invalid environment variable name: {key}"));
        }
        env_vars.insert(key.to_string(), value.to_string());
    }

    env_vars
        .entry("PATH".into())
        .or_insert_with(|| environment_file_path().unwrap_or_else(|| DEFAULT_PATH.into()));

    env_vars
        .into_iter()
        .map(|(key, value)| {
            CString::new(format!("{key}={value}"))
                .map_err(|_| "environment contains NUL byte".to_string())
        })
        .collect()
}

fn environment_file_path() -> Option<String> {
    let contents = fs::read_to_string("/etc/environment").ok()?;

    contents.lines().find_map(|line| {
        let line = line.trim();
        let line = line.strip_prefix("export ").unwrap_or(line);
        let (key, value) = line.split_once('=')?;

        if key.trim() != "PATH" {
            return None;
        }

        let value = value.split_once('#').map_or(value, |(value, _)| value);
        let value = value.trim();

        let value = value
            .strip_prefix('"')
            .and_then(|value| value.strip_suffix('"'))
            .or_else(|| {
                value
                    .strip_prefix('\'')
                    .and_then(|value| value.strip_suffix('\''))
            })
            .unwrap_or(value);

        Some(value.to_string())
    })
}
