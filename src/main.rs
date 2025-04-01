use getopts::Options;
use nix::sys::stat::{self, Mode};
use nix::unistd::{self, Uid, Gid, User};
use std::{env, process};
use std::ffi::CString;
use std::fs::File;
use std::io::{self, BufRead};
use std::path::{Path, PathBuf};

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
    opts.optopt("", "environ", "Environment policy: safe (default), none, or all", "MODE");
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

    let env: Vec<CString> = match matches.opt_str("environ").unwrap_or_else(|| "safe".to_string()).as_str() {
        "none" => Vec::new(),
        "all" => {
            env::vars()
                .map(|(key, value)| CString::new(format!("{}={}", key, value)).unwrap())
                .collect()
        },
        "safe" | _ => build_safe_env(new_euid),
    };

    if let Err(err) = unistd::setresgid(new_rgid, new_egid, Gid::from_raw(u32::MAX)) {
        eprintln!("{}: {}", path.display(), err);
        process::exit(1);
    }
    if let Err(err) = unistd::setresuid(new_ruid, new_euid, Uid::from_raw(u32::MAX)) {
        eprintln!("{}: {}", path.display(), err);
        process::exit(1);
    }

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

fn build_safe_env(uid: Uid) -> Vec<CString> {
    let mut env_vars = Vec::new();

    let target_user = User::from_uid(uid)
        .expect(&format!("Failed to look up user by uid: {}", uid))
        .expect(&format!("No user found for uid: {}", uid));

    let init_environ = std::fs::read("/proc/1/environ")
        .expect("Failed to read init environ");
    let path_value = String::from_utf8_lossy(&init_environ)
        .split('\0')
        .find(|s| s.starts_with("PATH="))
        .expect("PATH not found in init environ")
        .to_string();
    env_vars.push(CString::new(path_value).unwrap());

    env_vars.push(CString::new(format!("LOGNAME={}", target_user.name)).unwrap());
    env_vars.push(CString::new(format!("USER={}", target_user.name)).unwrap());
    env_vars.push(CString::new(format!("HOME={}", target_user.dir)).unwrap());
    env_vars.push(CString::new(format!("SHELL={}", target_user.shell)).unwrap());
    env_vars.push(CString::new(format!("MAIL=/var/mail/{}", target_user.name)).unwrap());

    let term = std::env::var("TERM").unwrap_or_else(|_| "unknown".to_string());
    env_vars.push(CString::new(format!("TERM={}", term)).unwrap());
    let lang = std::env::var("LANG").unwrap_or_else(|_| "en_US.UTF-8".to_string());
    env_vars.push(CString::new(format!("LANG={}", lang)).unwrap());

    for (key, value) in std::env::vars() {
        if ["LANGUAGE", "TZ", "LS_COLORS"].contains(&key.as_str()) || key.starts_with("LC_") {
            env_vars.push(CString::new(format!("{}={}", key, value)).unwrap());
        }
    }

    env_vars
}
