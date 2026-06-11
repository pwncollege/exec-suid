use getopts::Options;
use nix::sys::resource::{self, Resource, rlim_t};
use nix::sys::stat::{self, Mode};
use nix::unistd::{self, Uid, Gid, User};
use std::{env, process};
use std::collections::BTreeMap;
use std::ffi::CString;
use std::fs::File;
use std::io::{self, BufRead, Read};
use std::path::{Path, PathBuf};

const DEFAULT_PATH: &str = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin";

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() <= 1 {
        eprintln!("Usage: {} [path]", args[0]);
        process::exit(1);
    }

    let path = Path::new(&args[if args.len() == 2 { 1 } else { 2 }]);
    if let Err(err) = validate_secure_path(path) {
        eprintln!("{}: {}", path.display(), err);
        process::exit(1);
    }
    let (exec_argv, mut script_argv) = parse_header(path).unwrap_or_else(|err| {
        eprintln!("{}: {}", path.display(), err);
        process::exit(1);
    });
    if exec_argv[0] != args[0] {
        eprintln!("{}: Executable path does not match", path.display());
        process::exit(1);
    }

    let mut opts = Options::new();
    opts.optflag("", "real", "Set real user and group IDs");
    // Deprecated: kept temporarily for compatibility. New scripts should rely on the safe default and --env overrides.
    opts.optopt("", "environ", "Environment policy: safe (default), none, or all", "MODE");
    opts.optmulti("", "env", "Set an environment variable in the invoked script", "KEY=VALUE");
    let matches = opts.parse(&exec_argv[1..]).unwrap();

    script_argv.push(path.to_str().unwrap().to_string());
    script_argv.extend_from_slice(&args[if args.len() == 2 { 2.. } else { 3.. }]);

    let stat = stat::stat(path).unwrap_or_else(|err| {
        eprintln!("{}: {}", path.display(), err);
        process::exit(1);
    });
    let mode = stat::Mode::from_bits_truncate(stat.st_mode);
    let real_uid = Uid::current();
    let real_gid = Gid::current();
    let new_euid = if mode.contains(Mode::S_ISUID) { Uid::from_raw(stat.st_uid) } else { real_uid };
    let new_egid = if mode.contains(Mode::S_ISGID) { Gid::from_raw(stat.st_gid) } else { real_gid };
    let (new_ruid, new_rgid) = if matches.opt_present("real") { (new_euid, new_egid) } else { (real_uid, real_gid) };

    let env = match matches.opt_str("environ").unwrap_or_else(|| "safe".into()).as_str() {
        "none" => Ok(Vec::new()),
        "all" => env::vars()
            .map(|(key, value)| CString::new(format!("{}={}", key, value)).map_err(|_| "environment contains NUL byte".to_string()))
            .collect(),
        "safe" | _ => build_safe_env(new_euid, &matches.opt_strs("env")),
    }.unwrap_or_else(|err| {
        eprintln!("{}: {}", path.display(), err);
        process::exit(1);
    });

    if let Err(err) = resource::setrlimit(Resource::RLIMIT_CORE, 0 as rlim_t, 0 as rlim_t) {
        eprintln!("{}: {}", path.display(), err);
        process::exit(1);
    }

    if let Err(err) = unistd::setresgid(new_rgid, new_egid, Gid::from_raw(u32::MAX)) {
        eprintln!("{}: {}", path.display(), err);
        process::exit(1);
    }
    if let Err(err) = unistd::setresuid(new_ruid, new_euid, Uid::from_raw(u32::MAX)) {
        eprintln!("{}: {}", path.display(), err);
        process::exit(1);
    }

    stat::umask(Mode::from_bits_truncate(0o022));

    unistd::execve(
        &CString::new(script_argv[0].clone()).unwrap(),
        &script_argv.iter().map(|arg| CString::new(arg.as_str()).unwrap()).collect::<Vec<_>>(),
        &env.iter().map(|var| var.as_c_str()).collect::<Vec<_>>(),
    ).unwrap_or_else(|err| {
        eprintln!("{}: {}", path.display(), err);
        process::exit(1);
    });
}

fn parse_header(path: &Path) -> io::Result<(Vec<String>, Vec<String>)> {
    let file = File::open(path)?;
    let reader = io::BufReader::new(file);
    let first_line = reader.lines().next().unwrap()?;
    if !first_line.starts_with("#!") {
        return Err(io::Error::new(io::ErrorKind::Other, "Header does not start with #!"));
    }
    let tokens: Vec<String> = first_line[2..].split_whitespace().map(String::from).collect();
    if let Some(split_index) = tokens.iter().position(|x| x == "--") {
        Ok((tokens[..split_index].to_vec(), tokens[split_index + 1..].to_vec()))
    } else {
        Err(io::Error::new(io::ErrorKind::Other, "Header does not contain a -- separator"))
    }
}

fn validate_secure_path(path: &Path) -> io::Result<()> {
    if !path.exists() {
        return Err(io::Error::new(io::ErrorKind::NotFound, "No such file or directory"));
    }
    let base_path = if path.is_relative() {
        std::env::current_dir()?
    } else {
        PathBuf::new()
    };
    let mut current_path = PathBuf::new();
    for component in base_path.components().chain(path.components()) {
        current_path.push(component);
        let stat = stat::lstat(&current_path)?;
        if stat.st_uid != 0 {
            return Err(io::Error::new(io::ErrorKind::Other, "File not hierarchically owned by root"));
        }
    }
    if check_path_in_nosuid_mount(path)? {
        return Err(io::Error::new(io::ErrorKind::Other, "File is in a nosuid mount"));
    }
    Ok(())
}

fn check_path_in_nosuid_mount(path: &Path) -> io::Result<bool> {
    let path = path.canonicalize().unwrap();
    let mounts = File::open("/proc/self/mounts")?;
    let reader = io::BufReader::new(mounts);
    if let Some(mount_options) = reader
        .lines()
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .rev()
        .filter_map(|line| {
            let parts: Vec<_> = line.split_whitespace().collect();
            if parts.len() >= 4 {
                let (point, options) = (&parts[1], &parts[3]);
                if path.starts_with(point) {
                    return Some(options.to_string());
                }
            }
            None
        })
        .next()
    {
        Ok(mount_options.split(',').any(|opt| opt == "nosuid"))
    } else {
        Err(io::Error::new(io::ErrorKind::Other, "File not in any mount"))
    }
}

fn build_safe_env(uid: Uid, env_overrides: &[String]) -> Result<Vec<CString>, String> {
    let mut env_vars: BTreeMap<String, String> = BTreeMap::new();

    match User::from_uid(uid).ok().flatten() {
        Some(user) => {
            env_vars.insert("USER".into(), user.name.clone());
            env_vars.insert("LOGNAME".into(), user.name);
            env_vars.insert("HOME".into(), user.dir.display().to_string());
            env_vars.insert("SHELL".into(), user.shell.display().to_string());
        }
        None => {
            env_vars.insert("USER".into(), format!("#{}", uid.as_raw()));
            env_vars.insert("LOGNAME".into(), format!("#{}", uid.as_raw()));
            env_vars.insert("HOME".into(), "/".into());
            env_vars.insert("SHELL".into(), "/bin/sh".into());
        }
    }

    let term = std::env::var("TERM").unwrap_or_else(|_| "unknown".into());
    env_vars.insert("TERM".into(), term);
    let lang = std::env::var("LANG").unwrap_or_else(|_| "C.UTF-8".into());
    env_vars.insert("LANG".into(), lang);

    for (key, value) in std::env::vars() {
        if ["LANGUAGE", "TZ", "DISPLAY", "LS_COLORS"].contains(&key.as_str()) || key.starts_with("LC_") {
            env_vars.insert(key, value);
        }
    }

    for item in env_overrides {
        let (key, value) = item
            .split_once('=')
            .ok_or_else(|| format!("--env requires KEY=VALUE: {item}"))?;
        if key.is_empty() || key.as_bytes().contains(&0) || key.as_bytes().contains(&b'=') {
            return Err(format!("invalid environment variable name: {key}"));
        }
        env_vars.insert(key.to_string(), value.to_string());
    }

    if !env_vars.contains_key("PATH") {
        env_vars.insert("PATH".into(), environment_file_path().unwrap_or_else(|| DEFAULT_PATH.into()));
    }

    env_vars
        .into_iter()
        .map(|(key, value)| CString::new(format!("{}={}", key, value)).map_err(|_| "environment contains NUL byte".to_string()))
        .collect()
}

fn environment_file_path() -> Option<String> {
    let mut data = String::new();
    File::open("/etc/environment").ok()?.read_to_string(&mut data).ok()?;
    data.lines().find_map(|line| {
        let mut line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            return None;
        }
        if let Some(rest) = line.strip_prefix("export ") {
            line = rest.trim_start();
        }
        line = line.split_once('#').map(|(value, _)| value).unwrap_or(line).trim_end();
        let (key, value) = line.split_once('=')?;
        if key.trim() != "PATH" {
            return None;
        }
        let value = value.trim();
        Some(if let Some(quote) = value.chars().next().filter(|quote| *quote == '"' || *quote == '\'') {
            let value = &value[1..];
            value.strip_suffix(quote).unwrap_or(value).to_string()
        } else {
            value.to_string()
        })
    })
}
