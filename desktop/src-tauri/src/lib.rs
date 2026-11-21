// Thin desktop shell: runs `reliontree watch` on the cluster through the system ssh (port forwarded),
// or locally through the bundled sidecar (PyInstaller build of reliontree, no Python needed),
// and shows the printed login address in its own window.
use std::io::{BufRead, BufReader, Read};
use std::path::Path;
use std::net::TcpListener;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_dialog::DialogExt;

/// The running ssh tunnel or local sidecar; stopped when its window closes.
struct Tunnel(Mutex<Option<Child>>);

const TRIES: usize = 5;
const TIMEOUT: Duration = Duration::from_secs(60);

// ---- pure helpers (unit-tested below) ----

/// The login address `reliontree watch` prints, e.g.
/// "reliontree watch: http://127.0.0.1:8710/?k=abc (refreshing every 10s, ...)".
/// Only accepted for the port we forwarded: the server checks the Host header.
pub fn parse_login_url(line: &str, port: u16) -> Option<String> {
    let prefix = format!("http://127.0.0.1:{port}/");
    let start = line.find(&prefix)?;
    let url: String = line[start..].chars().take_while(|c| !c.is_whitespace()).collect();
    url.contains("?k=").then_some(url)
}

/// ssh (local bind) or Python on the cluster (remote bind) reports a busy port.
pub fn port_in_use(output: &str) -> bool {
    let o = output.to_lowercase();
    o.contains("address already in use") || o.contains("could not request local forwarding")
}

/// A port in 20000..60000 not tried yet that `is_free` accepts. The seed spreads users of a
/// shared login node over the range; the local side must be free too (same number both ends).
pub fn pick_port(seed: u64, tried: &[u16], is_free: impl Fn(u16) -> bool) -> Option<u16> {
    (0..500u64)
        .map(|i| 20000 + ((seed + i * 7919) % 40000) as u16)
        .find(|p| !tried.contains(p) && is_free(*p))
}

/// Single-quote for the remote POSIX shell.
pub fn sh_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', r"'\''"))
}

/// Host/user go to ssh as arguments: refuse empty, whitespace and a leading '-' (option injection).
pub fn valid_word(s: &str) -> bool {
    !s.is_empty() && !s.starts_with('-') && !s.chars().any(|c| c.is_whitespace() || c.is_control())
}

pub fn ssh_args(host: &str, user: &str, ssh_port: Option<u16>, project: &str, port: u16) -> Vec<String> {
    let mut a: Vec<String> = [
        "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
        // -tt: a pty, so the server on the cluster gets SIGHUP and stops when we kill ssh
        "-tt",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    a.push("-L".into());
    a.push(format!("{port}:127.0.0.1:{port}"));
    if let Some(p) = ssh_port {
        a.push("-p".into());
        a.push(p.to_string());
    }
    if !user.is_empty() {
        a.push("-l".into());
        a.push(user.into());
    }
    a.push(host.into());
    let proj = if project.is_empty() { String::new() } else { format!("{} ", sh_quote(project)) };
    a.push(format!("exec reliontree watch {proj}--no-open --port {port}"));
    a
}

/// Arguments for the bundled sidecar (local mode). No `--` needed: the folder comes from the dialog (absolute path).
pub fn local_args(folder: &str, port: u16) -> Vec<String> {
    vec!["watch".into(), "--no-open".into(), "--port".into(), port.to_string(), folder.into()]
}

/// Short, actionable error from what ssh/the cluster printed.
pub fn explain(output: &str) -> String {
    let o = output.to_lowercase();
    let hint = if o.contains("permission denied") {
        "ssh needs a key or a running ssh agent (passwords and 2FA prompts are not shown here). Run `ssh <host>` once in a terminal."
    } else if o.contains("host key verification failed") {
        "The cluster's host key is not known yet. Run `ssh <host>` once in a terminal and accept it."
    } else if o.contains("command not found") || (o.contains("not found") && o.contains("reliontree")) {
        "`reliontree` is not on the PATH of a non-interactive shell on the cluster (pip install --user, or add it to ~/.bashrc)."
    } else if o.contains("default_pipeline.star") || o.contains("no relion project") {
        "The project folder is not a RELION project (no default_pipeline.star)."
    } else {
        "ssh or reliontree stopped."
    };
    let tail: Vec<&str> = output.lines().rev().take(6).collect::<Vec<_>>().into_iter().rev().collect();
    format!("{hint}\n\n{}", tail.join("\n"))
}

// ---- process handling ----

fn no_window(cmd: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW: no console flashing up
    }
    let _ = cmd;
}

fn local_free(p: u16) -> bool {
    TcpListener::bind(("127.0.0.1", p)).is_ok()
}

#[tauri::command]
fn check_ssh() -> Result<String, String> {
    let mut cmd = Command::new("ssh");
    cmd.arg("-V").stdin(Stdio::null());
    no_window(&mut cmd);
    match cmd.output() {
        Ok(out) => Ok(String::from_utf8_lossy(&out.stderr).trim().to_string()),
        Err(_) if cfg!(windows) => Err("No ssh client found. Install the OpenSSH client: Settings > System > Optional features > Add a feature > OpenSSH Client.".into()),
        Err(_) => Err("No ssh client found on the PATH. Install OpenSSH (package openssh-client).".into()),
    }
}

/// Start `program`, wait for the login address. Ok((child, url)), Err((busy_port, message)).
fn try_once(program: &Path, args: &[String], port: u16) -> Result<(Child, String), (bool, String)> {
    let mut cmd = Command::new(program);
    cmd.args(args).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    no_window(&mut cmd);
    let mut child = cmd.spawn().map_err(|e| (false, format!("could not start {}: {e}", program.display())))?;
    let (tx, rx) = mpsc::channel::<String>();
    // keep draining both pipes for the life of ssh so it never blocks on a full pipe
    fn pump(r: impl Read + Send + 'static, tx: mpsc::Sender<String>) {
        std::thread::spawn(move || {
            for line in BufReader::new(r).lines().map_while(Result::ok) {
                let _ = tx.send(line);
            }
        });
    }
    pump(child.stdout.take().unwrap(), tx.clone());
    pump(child.stderr.take().unwrap(), tx);
    let mut seen = String::new();
    let end = Instant::now() + TIMEOUT;
    loop {
        match rx.recv_timeout(end.saturating_duration_since(Instant::now())) {
            Ok(line) => {
                if let Some(url) = parse_login_url(&line, port) {
                    return Ok((child, url));
                }
                seen.push_str(line.trim_end_matches('\r'));
                seen.push('\n');
            }
            Err(e) => {
                let _ = child.kill();
                let _ = child.wait();
                if matches!(e, mpsc::RecvTimeoutError::Timeout) {
                    return Err((false, format!("No login address from reliontree after {}s.\n\n{seen}", TIMEOUT.as_secs())));
                }
                return Err((port_in_use(&seen), explain(&seen)));
            }
        }
    }
}

/// Start `program` with `args(port)` on free ports until one works (busy port: next one).
async fn start_server(program: std::path::PathBuf, args: impl Fn(u16) -> Vec<String> + Send + 'static) -> Result<(Child, String), String> {
    let seed = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_nanos() as u64).unwrap_or(0);
    tauri::async_runtime::spawn_blocking(move || {
        let mut tried = Vec::new();
        let mut last = String::new();
        for _ in 0..TRIES {
            let port = pick_port(seed, &tried, local_free).ok_or("no free local port")?;
            tried.push(port);
            match try_once(&program, &args(port), port) {
                Ok(ok) => return Ok(ok),
                Err((true, msg)) => last = msg, // busy on either end: next port
                Err((false, msg)) => return Err(msg),
            }
        }
        Err(format!("Every port tried was busy.\n\n{last}"))
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn connect(app: tauri::AppHandle, host: String, user: String, ssh_port: Option<u16>, project: String) -> Result<(), String> {
    let (host, user, project) = (host.trim().to_string(), user.trim().to_string(), project.trim().to_string());
    if !valid_word(&host) || !(user.is_empty() || valid_word(&user)) {
        return Err("Host and user must be single words that do not start with '-'.".into());
    }
    check_ssh()?;
    let (child, url) = start_server("ssh".into(), move |port| ssh_args(&host, &user, ssh_port, &project, port)).await?;
    open_view(&app, child, url)
}

#[tauri::command]
async fn pick_folder(app: tauri::AppHandle) -> Option<String> {
    let dir = app.dialog().file().set_title("RELION project folder").blocking_pick_folder()?;
    Some(dir.into_path().ok()?.to_string_lossy().into_owned())
}

#[tauri::command]
async fn open_local(app: tauri::AppHandle, folder: String) -> Result<(), String> {
    if !Path::new(&folder).is_dir() {
        return Err(format!("Not a folder: {folder}"));
    }
    // externalBin: Tauri puts the sidecar next to the app's own binary, without the target-triple suffix
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let sidecar = exe.with_file_name(format!("reliontree-cli{}", std::env::consts::EXE_SUFFIX));
    let (child, url) = start_server(sidecar, move |port| local_args(&folder, port)).await?;
    open_view(&app, child, url)
}

fn open_view(app: &tauri::AppHandle, child: Child, url: String) -> Result<(), String> {
    *app.state::<Tunnel>().0.lock().unwrap() = Some(child);
    let handle = app.clone();
    WebviewWindowBuilder::new(app, "view", WebviewUrl::External(url.parse().map_err(|_| "bad address")?))
        .title("reliontree")
        .inner_size(1400.0, 900.0)
        .build()
        .map_err(|e| e.to_string())?
        .on_window_event(move |ev| {
            if let tauri::WindowEvent::Destroyed = ev {
                stop_tunnel(&handle);
                if let Some(w) = handle.get_webview_window("start") {
                    let _ = w.show();
                }
            }
        });
    if let Some(w) = app.get_webview_window("start") {
        let _ = w.hide();
    }
    Ok(())
}

/// Ask politely, then force. The sidecar is a PyInstaller --onefile build: a bootloader whose child is the real
/// Python process. A bare kill (SIGKILL / TerminateProcess) of the bootloader would leave that child running.
fn stop_tunnel(app: &tauri::AppHandle) {
    let Some(mut c) = app.state::<Tunnel>().0.lock().unwrap().take() else { return };
    let pid = c.id().to_string();
    // Unix: SIGTERM, which the bootloader forwards to Python (ssh exits on it too). Windows: end the whole tree.
    let mut cmd = if cfg!(windows) { Command::new("taskkill") } else { Command::new("kill") };
    if cfg!(windows) { cmd.args(["/T", "/F", "/PID", &pid]) } else { cmd.args(["-TERM", &pid]) };
    cmd.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    no_window(&mut cmd);
    let _ = cmd.status();
    let end = Instant::now() + Duration::from_secs(5);
    while Instant::now() < end {
        if let Ok(Some(_)) = c.try_wait() {
            return;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    let _ = c.kill();
    let _ = c.wait();
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Tunnel(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![check_ssh, connect, pick_folder, open_local])
        .build(tauri::generate_context!())
        .expect("error while building reliontree")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                stop_tunnel(app);
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn login_url_from_watch_output() {
        let line = "reliontree watch: http://127.0.0.1:8710/?k=Ab-3_x (refreshing every 10s, Ctrl-C to stop)";
        assert_eq!(parse_login_url(line, 8710).as_deref(), Some("http://127.0.0.1:8710/?k=Ab-3_x"));
        assert_eq!(parse_login_url(&format!("{line}\r"), 8710).as_deref(), Some("http://127.0.0.1:8710/?k=Ab-3_x"));
        assert_eq!(parse_login_url(line, 8711), None); // other port: Host check would 403
        assert_eq!(parse_login_url("then open http://127.0.0.1:8710/ in a browser", 8710), None); // no login code
        assert_eq!(parse_login_url("on your own computer:  ssh -L 8710:127.0.0.1:8710 node1", 8710), None);
    }

    #[test]
    fn busy_port_detection() {
        assert!(port_in_use("reliontree: [Errno 98] Address already in use\n"));
        assert!(port_in_use("bind [127.0.0.1]:8710: Address already in use\nchannel_setup_fwd_listener_tcpip: cannot listen to port: 8710\nCould not request local forwarding.\n"));
        assert!(!port_in_use("Permission denied (publickey).\n"));
    }

    #[test]
    fn pick_port_skips_tried_and_busy() {
        let p = pick_port(0, &[], |_| true).unwrap();
        assert!((20000..60000).contains(&p));
        let q = pick_port(0, &[p], |_| true).unwrap();
        assert_ne!(p, q);
        let r = pick_port(0, &[], |x| x != p).unwrap();
        assert_ne!(r, p);
        assert_eq!(pick_port(0, &[], |_| false), None);
        assert!((20000..60000).contains(&pick_port(u64::MAX / 2, &[], |_| true).unwrap()));
    }

    #[test]
    fn quoting_and_validation() {
        assert_eq!(sh_quote("/data/my proj"), "'/data/my proj'");
        assert_eq!(sh_quote("it's"), r"'it'\''s'");
        assert!(valid_word("login.cluster"));
        assert!(!valid_word("-oProxyCommand=x"));
        assert!(!valid_word("a b"));
        assert!(!valid_word(""));
    }

    #[test]
    fn ssh_command_line() {
        let a = ssh_args("hpc", "lukas", Some(2222), "/data/p 1", 30001);
        assert!(a.windows(2).any(|w| w == ["-o", "BatchMode=yes"]));
        assert!(a.windows(2).any(|w| w == ["-L", "30001:127.0.0.1:30001"]));
        assert!(a.windows(2).any(|w| w == ["-p", "2222"]));
        assert!(a.windows(2).any(|w| w == ["-l", "lukas"]));
        assert_eq!(a[a.len() - 2], "hpc");
        assert_eq!(a.last().unwrap(), "exec reliontree watch '/data/p 1' --no-open --port 30001");
        let b = ssh_args("hpc", "", None, "", 30001);
        assert!(!b.contains(&"-p".to_string()) && !b.contains(&"-l".to_string()));
        assert_eq!(b.last().unwrap(), "exec reliontree watch --no-open --port 30001");
    }

    #[test]
    fn local_command_line() {
        assert_eq!(local_args("/data/my proj", 30002), ["watch", "--no-open", "--port", "30002", "/data/my proj"]);
    }

    #[test]
    fn explain_gives_hint_and_tail() {
        let m = explain("Permission denied (publickey,keyboard-interactive).\n");
        assert!(m.starts_with("ssh needs a key"));
        assert!(m.contains("Permission denied (publickey"));
        assert!(explain("bash: reliontree: command not found\n").contains("PATH"));
    }
}
