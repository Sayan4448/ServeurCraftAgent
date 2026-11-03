//! Process Java d'un serveur : console, commandes, joueurs, arrêt propre.
//! Les threads de lecture remplissent `State` ; l'interface le lit à chaque
//! image (aucun widget touché depuis un thread).
use anyhow::{Result, bail};
use regex::Regex;
use std::collections::{BTreeSet, VecDeque};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, LazyLock, Mutex};
use std::time::{Duration, Instant};

use crate::{launch, meta, playit};

const MAX_LINES: usize = 4000;
const STOP_TIMEOUT: Duration = Duration::from_secs(30);

static ANSI: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\x1b\[[0-9;?]*[A-Za-z]|[\x{fffd}\x1b]?\[[0-9;]*m").unwrap());
// pseudo Java (3–16) ou Bedrock via Floodgate (préfixe « . » ou « * »)
static JOIN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\]:\s*([.*]?[A-Za-z0-9_]{3,16}) joined the game").unwrap());
static LEAVE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\]:\s*([.*]?[A-Za-z0-9_]{3,16}) (?:left the game|lost connection)").unwrap()
});

#[derive(Default)]
struct State {
    lines: VecDeque<String>,
    seq: u64, // nombre total de lignes ajoutées
    starting: bool,
    ready: bool,
    stopping: bool,
    players: BTreeSet<String>,
    started_at: Option<Instant>,
}

#[derive(Clone, Debug, Default)]
pub struct Status {
    pub running: bool,
    pub starting: bool,
    pub ready: bool,
    pub stopping: bool,
    pub players: Vec<String>,
    pub uptime: Option<Duration>,
}

#[derive(Clone)]
pub struct ServerProcess {
    pub name: String,
    pub dir: PathBuf,
    state: Arc<Mutex<State>>,
    child: Arc<Mutex<Option<Child>>>,
    stdin: Arc<Mutex<Option<ChildStdin>>>,
}

impl ServerProcess {
    pub fn new(name: &str, dir: PathBuf) -> Self {
        Self {
            name: name.into(),
            dir,
            state: Default::default(),
            child: Default::default(),
            stdin: Default::default(),
        }
    }

    pub fn log(&self, line: &str) {
        let mut st = self.state.lock().unwrap();
        st.lines.push_back(line.to_string());
        while st.lines.len() > MAX_LINES {
            st.lines.pop_front();
        }
        st.seq += 1;
    }

    /// Lignes ajoutées depuis `seq` (et le nouveau compteur).
    pub fn lines_since(&self, seq: u64) -> (Vec<String>, u64) {
        let st = self.state.lock().unwrap();
        let n = (st.seq.saturating_sub(seq) as usize).min(st.lines.len());
        let skip = st.lines.len() - n;
        (st.lines.iter().skip(skip).cloned().collect(), st.seq)
    }

    pub fn is_running(&self) -> bool {
        let mut child = self.child.lock().unwrap();
        match child.as_mut() {
            Some(c) => matches!(c.try_wait(), Ok(None)),
            None => false,
        }
    }

    pub fn status(&self) -> Status {
        let running = self.is_running();
        let st = self.state.lock().unwrap();
        Status {
            running,
            starting: st.starting,
            ready: running && st.ready,
            stopping: running && st.stopping,
            players: if running { st.players.iter().cloned().collect() } else { vec![] },
            uptime: st.started_at.filter(|_| running).map(|t| t.elapsed()),
        }
    }

    /// Démarre le serveur dans un thread (Java peut être téléchargé).
    pub fn start(&self) {
        {
            let mut st = self.state.lock().unwrap();
            if st.starting || self.child.lock().unwrap().as_mut().is_some_and(|c| matches!(c.try_wait(), Ok(None))) {
                return;
            }
            st.starting = true;
        }
        self.log(&format!("── Démarrage de {}… ──", self.name));
        let me = self.clone();
        std::thread::spawn(move || {
            if let Err(e) = me.spawn_java() {
                me.log(&format!("✖ Impossible de démarrer le serveur : {e:#}"));
            }
            me.state.lock().unwrap().starting = false;
        });
    }

    fn spawn_java(&self) -> Result<()> {
        let m = meta::load(&self.dir)?;
        let port = launch::server_port(&self.dir, &m);
        if launch::port_in_use(port) {
            bail!("le port {port} est déjà utilisé (autre serveur ou programme)");
        }
        let log = |s: &str| self.log(s);
        let (java, args) = launch::build_command(&self.dir, &m, &log)?;
        let mut cmd = Command::new(&java);
        cmd.args(&args)
            .current_dir(&self.dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        }
        let mut child = cmd.spawn()?;
        {
            let mut st = self.state.lock().unwrap();
            st.ready = false;
            st.stopping = false;
            st.players.clear();
            st.started_at = Some(Instant::now());
        }
        *self.stdin.lock().unwrap() = child.stdin.take();
        if let Some(out) = child.stdout.take() {
            self.reader(out);
        }
        if let Some(err) = child.stderr.take() {
            self.reader(err);
        }
        *self.child.lock().unwrap() = Some(child);
        self.waiter();
        if m.get("playit_auto").and_then(|v| v.as_bool()) == Some(true) && playit::linked() {
            self.tunnels();
        }
        Ok(())
    }

    fn reader(&self, stream: impl Read + Send + 'static) {
        let me = self.clone();
        std::thread::spawn(move || {
            let mut r = BufReader::new(stream);
            let mut buf = vec![];
            while r.read_until(b'\n', &mut buf).unwrap_or(0) > 0 {
                let raw = String::from_utf8_lossy(&buf);
                let line = ANSI.replace_all(raw.trim_end_matches(['\r', '\n']), "").to_string();
                buf.clear();
                me.feed(&line);
            }
        });
    }

    fn feed(&self, line: &str) {
        {
            let mut st = self.state.lock().unwrap();
            if !st.ready && line.contains("Done (") {
                st.ready = true;
            }
            if let Some(c) = JOIN.captures(line) {
                st.players.insert(c[1].to_string());
            }
            if let Some(c) = LEAVE.captures(line) {
                st.players.remove(&c[1]);
            }
        }
        self.log(line);
    }

    fn waiter(&self) {
        let me = self.clone();
        std::thread::spawn(move || {
            loop {
                std::thread::sleep(Duration::from_millis(500));
                let code = match me.child.lock().unwrap().as_mut().map(|c| c.try_wait()) {
                    Some(Ok(None)) => continue,
                    Some(Ok(Some(s))) => s.code(),
                    _ => None,
                };
                *me.stdin.lock().unwrap() = None;
                me.log(&match code {
                    Some(0) => "── Serveur arrêté ──".to_string(),
                    Some(c) => format!("── Serveur arrêté (code {c}) ──"),
                    None => "── Serveur arrêté ──".to_string(),
                });
                return;
            }
        });
    }

    /// Envoie une commande à la console (sans « / »).
    pub fn send(&self, cmd: &str) -> bool {
        let cmd = cmd.trim().trim_start_matches('/');
        let mut stdin = self.stdin.lock().unwrap();
        match stdin.as_mut() {
            Some(s) if !cmd.is_empty() => {
                writeln!(s, "{cmd}").and_then(|_| s.flush()).is_ok()
            }
            _ => false,
        }
    }

    /// Arrêt propre (`stop`), puis kill si le serveur ne s'arrête pas.
    pub fn stop(&self) {
        if !self.is_running() {
            return;
        }
        self.state.lock().unwrap().stopping = true;
        self.log("── Arrêt demandé… ──");
        self.send("stop");
        let me = self.clone();
        std::thread::spawn(move || me.wait_or_kill(STOP_TIMEOUT));
    }

    /// Bloque jusqu'à l'arrêt, kill au-delà de `timeout`.
    pub fn wait_or_kill(&self, timeout: Duration) {
        let end = Instant::now() + timeout;
        while self.is_running() {
            if Instant::now() > end {
                if let Some(c) = self.child.lock().unwrap().as_mut() {
                    let _ = c.kill();
                }
                self.log("── Le serveur ne répondait plus : arrêt forcé ──");
                return;
            }
            std::thread::sleep(Duration::from_millis(250));
        }
    }

    /// Tunnels Playit (création / récupération) dans un thread.
    pub fn tunnels(&self) {
        let me = self.clone();
        std::thread::spawn(move || {
            let log = |ev: playit::Event| match ev {
                playit::Event::Create { label, local } => {
                    me.log(&format!("Playit : création du tunnel {label} (port local {local})…"))
                }
                playit::Event::Ready { label, address } => {
                    me.log(&format!("Playit : {label} → {address}"))
                }
                playit::Event::Agent => me.log("Playit : agent lancé"),
            };
            if let Err(e) = playit::setup_server(&me.name, &me.dir, &log) {
                me.log(&format!("✖ Playit : {}", playit::explain(&e)));
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn players_and_ready_from_console() {
        let p = ServerProcess::new("t", PathBuf::from("."));
        p.feed("[12:00:00] [Server thread/INFO]: Done (3.2s)! For help, type \"help\"");
        p.feed("[12:00:01] [Server thread/INFO]: Steve joined the game");
        p.feed("[12:00:02] [Server thread/INFO]: .BedrockGuy joined the game");
        p.feed("[12:00:03] [Server thread/INFO]: Steve left the game");
        let st = p.state.lock().unwrap();
        assert!(st.ready);
        assert_eq!(st.players.iter().cloned().collect::<Vec<_>>(), [".BedrockGuy"]);
    }

    #[test]
    fn lines_since_returns_only_new_lines() {
        let p = ServerProcess::new("t", PathBuf::from("."));
        p.log("a");
        let (_, seq) = p.lines_since(0);
        p.log("b");
        p.log("c");
        assert_eq!(p.lines_since(seq), (vec!["b".to_string(), "c".to_string()], 3));
    }

    #[test]
    fn ansi_colors_are_removed() {
        assert_eq!(ANSI.replace_all("\x1b[32mOK\x1b[0m", ""), "OK");
    }
}
