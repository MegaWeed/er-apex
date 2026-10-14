//! er-apex's first-launch setup (Melty's `setup` step): runs `setup.ps1` beside this exe with the
//! Windows PowerShell every Windows has, in this console, and returns its exit code. On a failure
//! the window stays open until Enter, so the player can read why.
use std::io::Read;
use std::process::{Command, ExitCode};

fn main() -> ExitCode {
    let exe = std::env::current_exe().expect("own path");
    let dir = exe.parent().expect("own folder");
    let script = dir.join("setup.ps1");
    let status = Command::new("powershell.exe")
        .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"])
        .arg(&script)
        .args(std::env::args_os().skip(1))
        .current_dir(dir)
        .status();
    let code = match status {
        Ok(s) => s.code().unwrap_or(1),
        Err(e) => {
            eprintln!("could not start PowerShell: {e}");
            1
        }
    };
    if code != 0 {
        eprintln!("\ner-apex setup did not finish (code {code}). Press Enter to close this window.");
        let _ = std::io::stdin().read(&mut [0u8]);
    }
    ExitCode::from(code.clamp(0, 255) as u8)
}
