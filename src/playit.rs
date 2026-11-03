//! Tunnels Playit.gg automatiques. Port de app/core/playit.py : liaison du
//! compte (claim), création des tunnels via l'API, agent officiel lancé en
//! arrière-plan. Fonctions bloquantes : à appeler depuis un thread.
use anyhow::{Result, anyhow, bail};
use regex::Regex;
use serde_json::{Value, json};
use std::hash::BuildHasher;
use std::io::BufRead;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{LazyLock, Mutex, MutexGuard};
use std::time::{Duration, Instant, SystemTime};

use crate::meta::{self, Meta};
use crate::{net, paths, voice};

const API: &str = "https://api.playit.gg";
const AGENT_VERSION: &str = "v1.0.10";
const CLAIM_URL: &str = "https://playit.gg/claim/";
const CLAIM_TIMEOUT: Duration = Duration::from_secs(600);
const AGENT_READY_TIMEOUT: Duration = Duration::from_secs(45);
const TUNNELS_TIMEOUT: Duration = Duration::from_secs(90);
pub const BEDROCK_PORT: u16 = 19132;

#[derive(Clone, Debug, PartialEq)]
pub struct Tunnel {
    pub name: String,
    pub proto: String, // "tcp" | "udp"
    pub address: String,
    pub local: u16,
}

/// Étapes de setup_server, pour l'affichage.
#[derive(Clone, Debug)]
pub enum Event {
    Create { label: String, local: u16 },
    Ready { label: String, address: String },
    Agent,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Kind {
    Java,
    Bedrock,
    Voice,
}

impl Kind {
    /// (tunnel_type de l'API, None = port libre ; type de port ; nom affiché)
    fn spec(self) -> (Option<&'static str>, &'static str, &'static str) {
        match self {
            Kind::Java => (Some("minecraft-java"), "tcp", "Java"),
            Kind::Bedrock => (Some("minecraft-bedrock"), "udp", "Bedrock"),
            Kind::Voice => (None, "udp", "Voice Chat"),
        }
    }
}

/// Message clair (français) pour une erreur Playit.
pub fn explain(e: &anyhow::Error) -> String {
    let msg = e.to_string();
    let fr = match msg.as_str() {
        "not linked" => "Compte Playit non lié.",
        "cancelled" => "Annulé.",
        "timeout" | "CodeExpired" => {
            "Délai dépassé : la page playit.gg n'a pas été validée à temps."
        }
        "rejected" | "UserRejected" => "Ajout refusé dans la page playit.gg.",
        "InvalidAgentKey" | "NoLongerValid" => {
            "La clé Playit n'est plus valide : délie puis relie le compte dans ⚙ Paramètres."
        }
        "RequiresVerifiedAccount" | "GuestAccountNotAllowed" => {
            "Playit demande un compte vérifié (e-mail) pour créer ce tunnel."
        }
        "RequiresPlayitPremium"
        | "PublicPortRequiresPlayitPremium"
        | "RegionRequiresPlayitPremium" => "Ce type de tunnel demande Playit Premium.",
        "AgentVersionTooOld" => {
            "Playit n'a pas encore reconnu l'agent de ce PC. Réessaie dans une minute ; si ça continue, \
             délie puis relie le compte dans ⚙ Paramètres."
        }
        _ => {
            return match msg.strip_prefix("pending: ") {
                Some(m) => format!("Tunnel en attente chez Playit : {m}"),
                None => format!("{e:#}"),
            };
        }
    };
    fr.to_string()
}

/// Les fonctions publiques renvoient des erreurs déjà en français.
fn french(e: anyhow::Error) -> anyhow::Error {
    anyhow!(explain(&e))
}

// ================================================================== API

fn call(path: &str, body: &Value, secret: Option<&str>) -> Result<Value> {
    let mut req = net::client()
        .post(format!("{API}{path}"))
        .json(body)
        .timeout(Duration::from_secs(15));
    if let Some(k) = secret.filter(|k| !k.is_empty()) {
        req = req.header("Authorization", format!("Agent-Key {k}"));
    }
    let r = req
        .send()
        .map_err(|e| anyhow!("playit.gg injoignable : {e}"))?;
    let code = r.status().as_u16();
    if code == 429 {
        bail!("playit.gg : trop de requêtes, réessaie dans 1 min.");
    }
    let j: Value = r
        .json()
        .map_err(|_| anyhow!("playit.gg : réponse HTTP {code}"))?;
    api_result(j)
}

/// `{status: "success", data}` -> data ; sinon le message d'erreur de l'API
/// (code comme « AgentVersionTooOld », traduit par explain()).
fn api_result(mut j: Value) -> Result<Value> {
    if j["status"] == "success" {
        return Ok(j.get_mut("data").map(Value::take).unwrap_or_default());
    }
    let data = &j["data"];
    let msg = data.get("message").unwrap_or(data);
    bail!("{}", val_str(msg))
}

/// str() Python d'une valeur JSON.
fn val_str(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        v => v.to_string(),
    }
}

fn list<'a>(v: &'a Value, key: &str) -> &'a [Value] {
    v[key].as_array().map(Vec::as_slice).unwrap_or(&[])
}

// ================================================================ secret

fn secret_file() -> PathBuf {
    paths::data_dir().join("playit.toml")
}

fn agent_dir() -> PathBuf {
    paths::runtimes_dir().join("playit")
}

fn parse_secret(text: &str) -> String {
    static RE: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r#"secret_key\s*=\s*"([^"]+)""#).expect("regex"));
    RE.captures(text)
        .map(|m| m[1].trim().to_string())
        .unwrap_or_default()
}

fn secret() -> String {
    parse_secret(&std::fs::read_to_string(secret_file()).unwrap_or_default())
}

pub fn linked() -> bool {
    !secret().is_empty()
}

fn save_secret(key: &str) -> Result<()> {
    let f = secret_file();
    if let Some(p) = f.parent() {
        std::fs::create_dir_all(p)?;
    }
    std::fs::write(f, format!("secret_key = \"{}\"\n", key.trim()))?;
    Ok(())
}

pub fn unlink() {
    stop_agent();
    std::fs::remove_file(secret_file()).ok();
}

// ================================================================ liaison

/// (code, url à ouvrir dans le navigateur)
pub fn new_claim() -> (String, String) {
    // shortcut: pas de crate rand ; RandomState a une clé SipHash tirée de
    // l'aléa de l'OS, assez pour un code de liaison à usage unique.
    let nanos = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let h = std::collections::hash_map::RandomState::new().hash_one((nanos, std::process::id()));
    let code = format!("{:010x}", h & 0xff_ffff_ffff);
    let url = format!("{CLAIM_URL}{code}");
    (code, url)
}

/// Attend la validation dans le navigateur puis enregistre la clé.
/// `on_status` : WaitingForUserVisit / WaitingForUser / UserAccepted.
pub fn link(code: &str, on_status: &dyn Fn(&str), cancel: &AtomicBool) -> Result<()> {
    link_inner(code, on_status, cancel).map_err(french)
}

fn link_inner(code: &str, on_status: &dyn Fn(&str), cancel: &AtomicBool) -> Result<()> {
    let end = Instant::now() + CLAIM_TIMEOUT;
    let pause = Duration::from_millis(1500);
    // même format que l'agent officiel (« playit 1.0.10 ») : l'API en tire
    // la version de l'agent
    let body = json!({"code": code, "agent_type": "self-managed",
                      "version": format!("playit {}", AGENT_VERSION.trim_start_matches('v'))});
    let mut last = None;
    loop {
        if cancel.load(Ordering::Relaxed) {
            bail!("cancelled");
        }
        if Instant::now() > end {
            bail!("timeout");
        }
        let state = val_str(&call("/claim/setup", &body, None)?);
        if last.as_ref() != Some(&state) {
            on_status(&state);
        }
        match state.as_str() {
            "UserRejected" => bail!("rejected"),
            "UserAccepted" => break,
            _ => {}
        }
        last = Some(state);
        std::thread::sleep(pause);
    }
    let key = loop {
        if cancel.load(Ordering::Relaxed) {
            bail!("cancelled");
        }
        match call("/claim/exchange", &json!({"code": code}), None) {
            Ok(data) => break data["secret_key"].as_str().unwrap_or("").to_string(),
            Err(e)
                if ["NotAccepted", "NotSetup"].contains(&e.to_string().as_str())
                    && Instant::now() <= end =>
            {
                std::thread::sleep(pause)
            }
            Err(e) => return Err(e),
        }
    };
    if key.trim().is_empty() {
        bail!("playit.gg n'a pas renvoyé de clé : réessaie la liaison.");
    }
    save_secret(&key)
}

// ================================================================ tunnels

fn field(tunnel: &Value, name: &str) -> String {
    let fields = list(&tunnel["agent_config"], "fields");
    fields
        .iter()
        .find(|f| f["name"] == name)
        .map(|f| val_str(&f["value"]))
        .unwrap_or_default()
}

fn matches(tunnel: &Value, kind: Kind, local: u16) -> bool {
    let (want_type, proto, _) = kind.spec();
    tunnel["port_type"] == proto
        && tunnel["tunnel_type"].as_str().filter(|s| !s.is_empty()) == want_type
        && field(tunnel, "local_port") == local.to_string()
}

fn server_port(m: &Meta) -> u16 {
    u16::try_from(meta::int_of(m, "port", 25565)).unwrap_or(25565)
}

/// Tunnels d'un serveur : Java en TCP et Bedrock en UDP (prêt si le
/// cross-play est activé plus tard), + un tunnel UDP sur le port du mod
/// vocal s'il est installé (même ajouté après la création : modpack,
/// gestionnaire de mods).
pub fn wanted_for(m: &Meta, dir: &Path) -> Vec<(Kind, u16)> {
    let port = server_port(m);
    let mut out = vec![(Kind::Java, port), (Kind::Bedrock, BEDROCK_PORT)];
    let loader = meta::str_of(m, "loader");
    let voice = voice::voice_mod(dir, loader, meta::str_of(m, "voice"));
    if voice != "none" {
        out.push((Kind::Voice, voice::voice_port(dir, loader, voice, port)));
    }
    out
}

/// Tunnels créés / retrouvés pour ce serveur, enregistrés dans
/// servercraft.json (`tunnels`, `playit_auto`), adresse vocale écrite dans
/// le mod vocal, agent démarré.
pub fn setup_server(name: &str, dir: &Path, log: &dyn Fn(Event)) -> Result<Vec<Tunnel>> {
    setup(name, dir, log).map_err(french)
}

fn setup(name: &str, dir: &Path, log: &dyn Fn(Event)) -> Result<Vec<Tunnel>> {
    let mut m = meta::load(dir)?;
    let found = ensure_tunnels(name, &wanted_for(&m, dir), log)?;
    let tunnels = merged(&found, &m);
    m.insert("tunnels".into(), Value::Array(tunnels.clone()));
    m.insert("playit_auto".into(), true.into());
    meta::save(dir, &m)?;
    let (loader, voice) = (meta::str_of(&m, "loader"), meta::str_of(&m, "voice"));
    voice::apply_tunnels(dir, loader, &tunnels, server_port(&m), voice)?;
    log(Event::Agent);
    Ok(found)
}

/// Tunnels trouvés + anciens tunnels qui ne visent pas le même
/// (proto, port local).
fn merged(found: &[Tunnel], m: &Meta) -> Vec<Value> {
    let old = m
        .get("tunnels")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[]);
    let same = |o: &Value| {
        found
            .iter()
            .any(|t| o["proto"] == t.proto.as_str() && val_str(&o["local"]) == t.local.to_string())
    };
    found
        .iter()
        .map(|t| json!({"name": t.name, "proto": t.proto, "address": t.address, "local": t.local, "playit": true}))
        .chain(old.iter().filter(|o| !same(o)).cloned())
        .collect()
}

/// Crée les tunnels manquants pour `server` et attend leurs adresses.
pub fn ensure_tunnels(
    server: &str,
    wanted: &[(Kind, u16)],
    log: &dyn Fn(Event),
) -> Result<Vec<Tunnel>> {
    let key = secret();
    let api = |path: &str, body: &Value| {
        if key.is_empty() {
            bail!("not linked");
        }
        call(path, body, Some(&key))
    };
    ensure_with(server, wanted, log, &api, &start_agent, &std::thread::sleep).map_err(french)
}

type Api<'a> = &'a dyn Fn(&str, &Value) -> Result<Value>;

/// ensure_tunnels avec l'API, le lancement de l'agent et l'attente
/// injectés (tests sans réseau).
fn ensure_with(
    server: &str,
    wanted: &[(Kind, u16)],
    log: &dyn Fn(Event),
    api: Api,
    start: &dyn Fn() -> Result<()>,
    sleep: &dyn Fn(Duration),
) -> Result<Vec<Tunnel>> {
    let rd = api("/v1/agents/rundata", &json!({}))?;
    let agent_id = rd["agent_id"].clone();
    start()?;
    for &(kind, local) in wanted {
        let tunnels = list(&rd, "tunnels");
        if tunnels.iter().any(|t| matches(t, kind, local)) {
            continue;
        }
        let name = tunnel_name(server, kind, local);
        if tunnels
            .iter()
            .chain(list(&rd, "pending"))
            .any(|p| p["name"] == name.as_str())
        {
            continue; // déjà en attente
        }
        let (tunnel_type, proto, label) = kind.spec();
        log(Event::Create {
            label: label.into(),
            local,
        });
        let body = json!({
            "name": name, "tunnel_type": tunnel_type, "port_type": proto,
            "port_count": 1, "enabled": true, "alloc": null,
            "firewall_id": null, "proxy_protocol": null,
            "origin": {"type": "agent", "data": {
                "agent_id": agent_id, "local_ip": "127.0.0.1", "local_port": local}},
        });
        create_tunnel(api, sleep, &body)?;
    }
    let end = Instant::now() + TUNNELS_TIMEOUT;
    loop {
        let rd = api("/v1/agents/rundata", &json!({}))?;
        let mut found = vec![];
        for &(kind, local) in wanted {
            let (_, proto, label) = kind.spec();
            let addr = list(&rd, "tunnels")
                .iter()
                .filter(|t| matches(t, kind, local))
                .find_map(|t| t["display_address"].as_str().filter(|a| !a.is_empty()));
            if let Some(a) = addr {
                found.push(Tunnel {
                    name: label.into(),
                    proto: proto.into(),
                    address: a.into(),
                    local,
                });
            }
        }
        if found.len() == wanted.len() {
            for t in &found {
                log(Event::Ready {
                    label: t.name.clone(),
                    address: t.address.clone(),
                });
            }
            return Ok(found);
        }
        if Instant::now() > end {
            let pend: Vec<&str> = list(&rd, "pending")
                .iter()
                .filter_map(|p| p["status_msg"].as_str())
                .filter(|s| !s.is_empty())
                .collect();
            if pend.is_empty() {
                bail!("timeout");
            }
            bail!("pending: {}", pend.join(", "));
        }
        sleep(Duration::from_secs(3));
    }
}

/// Crée un tunnel. Juste après la liaison, l'agent n'a pas encore annoncé
/// sa version : l'API répond AgentVersionTooOld le temps qu'il se connecte.
fn create_tunnel(api: Api, sleep: &dyn Fn(Duration), body: &Value) -> Result<()> {
    let end = Instant::now() + AGENT_READY_TIMEOUT;
    loop {
        match api("/tunnels/create", body) {
            Ok(_) => return Ok(()),
            Err(e) if e.to_string() == "AgentVersionTooOld" && Instant::now() <= end => {
                sleep(Duration::from_secs(2))
            }
            Err(e) => return Err(e),
        }
    }
}

fn tunnel_name(server: &str, kind: Kind, local: u16) -> String {
    let base: String = format!("SC {server}")
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || " _.-".contains(*c))
        .take(40)
        .collect();
    let mut label = kind.spec().2.to_string();
    // port dans le nom : un ancien tunnel vocal sur un autre port (Plasmo
    // Voice visait 24454) ne bloque pas la création du bon
    if kind == Kind::Voice && local != 0 && local != voice::DEFAULT_VOICE_PORT {
        label += &format!(" {local}");
    }
    format!("{} {label}", base.trim())
        .chars()
        .take(60)
        .collect()
}

// ================================================================ agent

static AGENT: Mutex<Option<Child>> = Mutex::new(None);
static TAIL: Mutex<Vec<String>> = Mutex::new(Vec::new());

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

fn running(slot: &mut Option<Child>) -> bool {
    slot.as_mut()
        .is_some_and(|c| matches!(c.try_wait(), Ok(None)))
}

fn ensure_agent_exe() -> Result<PathBuf> {
    if !cfg!(windows) {
        bail!(
            "L'agent Playit n'existe que pour Windows : tunnels automatiques indisponibles sur ce système."
        );
    }
    static DOWNLOAD: Mutex<()> = Mutex::new(());
    let _one_at_a_time = lock(&DOWNLOAD); // même fichier .part sinon
    let exe = agent_dir().join(format!("playit-{AGENT_VERSION}.exe"));
    if !exe.exists() {
        let url = format!(
            "https://github.com/playit-cloud/playit-agent/releases/download/{AGENT_VERSION}/playit-windows-x86_64-signed.exe"
        );
        net::download(&url, &exe, None)
            .map_err(|e| anyhow!("Téléchargement de l'agent Playit impossible : {e:#}"))?;
    }
    Ok(exe)
}

pub fn agent_running() -> bool {
    running(&mut lock(&AGENT))
}

/// Dernière erreur de l'agent s'il s'est arrêté tout seul.
pub fn agent_error() -> String {
    let mut slot = lock(&AGENT);
    if slot.is_none() || running(&mut slot) {
        return String::new();
    }
    lock(&TAIL)
        .iter()
        .rev()
        .find(|l| !l.trim().is_empty())
        .cloned()
        .unwrap_or_default()
}

/// Lance l'agent playit (une seule instance pour tous les serveurs).
fn start_agent() -> Result<()> {
    if agent_running() {
        return Ok(());
    }
    let key = secret();
    if key.is_empty() {
        bail!("not linked");
    }
    // téléchargement hors du verrou : agent_running() (interface) ne bloque pas
    let exe = ensure_agent_exe()?;
    let mut slot = lock(&AGENT);
    if running(&mut slot) {
        return Ok(()); // lancé entre-temps par un autre serveur
    }
    lock(&TAIL).clear();
    let (reader, writer) = std::io::pipe()?;
    let mut cmd = Command::new(exe);
    cmd.arg("--secret")
        .arg(&key)
        .arg("--log-path")
        .arg(agent_dir().join("agent.log"));
    cmd.stdout(writer.try_clone()?).stderr(writer);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let child = cmd
        .spawn()
        .map_err(|e| anyhow!("Impossible de lancer l'agent Playit : {e}"))?;
    drop(cmd); // ferme nos copies du tuyau : drain() s'arrête quand l'agent quitte
    std::thread::spawn(move || drain(reader));
    *slot = Some(child);
    Ok(())
}

/// Garde les 30 dernières lignes de sortie de l'agent (pour agent_error).
fn drain(reader: std::io::PipeReader) {
    let mut r = std::io::BufReader::new(reader);
    let mut buf = vec![];
    while matches!(r.read_until(b'\n', &mut buf), Ok(n) if n > 0) {
        let mut tail = lock(&TAIL);
        tail.push(String::from_utf8_lossy(&buf).trim_end().to_string());
        let extra = tail.len().saturating_sub(30);
        tail.drain(..extra);
        buf.clear();
    }
}

pub fn stop_agent() {
    if let Some(mut c) = lock(&AGENT).take() {
        // Python : terminate() puis kill() ; sous Windows c'est le même
        // TerminateProcess
        c.kill().ok();
        c.wait().ok();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::{Cell, RefCell};

    /// L'agent est lancé avant la création, et un refus AgentVersionTooOld
    /// (agent pas encore connecté) est retenté au lieu d'échouer.
    #[test]
    fn tunnels_created_once_agent_is_known() {
        let calls = RefCell::new(Vec::<String>::new());
        let refused = Cell::new(1);
        let tunnels = RefCell::new(json!([]));
        let api = |path: &str, body: &Value| -> Result<Value> {
            calls.borrow_mut().push(path.into());
            if path == "/v1/agents/rundata" {
                return Ok(
                    json!({"agent_id": "a1", "tunnels": tunnels.borrow().clone(), "pending": []}),
                );
            }
            assert!(path == "/tunnels/create" && calls.borrow().iter().any(|c| c == "start"));
            if refused.get() > 0 {
                refused.set(refused.get() - 1);
                bail!("AgentVersionTooOld");
            }
            assert_eq!(
                body["origin"]["data"],
                json!({"agent_id": "a1", "local_ip": "127.0.0.1", "local_port": 25565})
            );
            *tunnels.borrow_mut() = json!([{
                "port_type": body["port_type"], "tunnel_type": body["tunnel_type"],
                "display_address": "x.tun.ply.gg",
                "agent_config": {"fields": [{"name": "local_port", "value": "25565"}]}}]);
            Ok(Value::Null)
        };
        let start = || {
            calls.borrow_mut().push("start".into());
            Ok(())
        };
        let events = RefCell::new(vec![]);
        let log = |e: Event| events.borrow_mut().push(e);
        let found = ensure_with(
            "survie",
            &[(Kind::Java, 25565)],
            &log,
            &api,
            &start,
            &|_| {},
        )
        .unwrap();
        let java = Tunnel {
            name: "Java".into(),
            proto: "tcp".into(),
            address: "x.tun.ply.gg".into(),
            local: 25565,
        };
        assert_eq!(found, vec![java]);
        assert_eq!(
            calls
                .borrow()
                .iter()
                .filter(|c| *c == "/tunnels/create")
                .count(),
            2
        );
        assert!(matches!(
            events.borrow()[..],
            [Event::Create { local: 25565, .. }, Event::Ready { .. }]
        ));
    }

    #[test]
    fn voice_chat_added_later_gets_its_udp_tunnel() {
        let dir = crate::voice::tests::temp("playit-wanted");
        std::fs::create_dir_all(dir.join("mods")).unwrap();
        std::fs::write(dir.join("mods/voicechat-fabric-1.21.4-2.5.26.jar"), b"j").unwrap();
        let m = json!({"port": 25565, "loader": "fabric", "voice": "none"})
            .as_object()
            .unwrap()
            .clone();
        let want = vec![
            (Kind::Java, 25565),
            (Kind::Bedrock, 19132),
            (Kind::Voice, 24454),
        ];
        assert_eq!(wanted_for(&m, &dir), want);
        assert_eq!(
            tunnel_name("plasmo", Kind::Voice, 25570),
            "SC plasmo Voice Chat 25570"
        );
        assert_eq!(
            tunnel_name("é/plasmo", Kind::Voice, 24454),
            "SC plasmo Voice Chat"
        );
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn merge_api_errors_and_secret() {
        let found = [Tunnel {
            name: "Java".into(),
            proto: "tcp".into(),
            address: "x:1".into(),
            local: 25565,
        }];
        let m = json!({"tunnels": [{"proto": "tcp", "local": "25565", "address": "old"},
                                   {"proto": "udp", "local": 24454, "address": "v"}]});
        let t = merged(&found, m.as_object().unwrap());
        assert_eq!(
            (t.len(), &t[0]["playit"], &t[1]["address"]),
            (2, &json!(true), &json!("v"))
        );
        let err = api_result(json!({"status": "error", "data": {"message": "UserRejected"}}))
            .unwrap_err();
        assert_eq!(explain(&err), "Ajout refusé dans la page playit.gg.");
        assert_eq!(
            explain(&anyhow!("pending: x")),
            "Tunnel en attente chez Playit : x"
        );
        assert_eq!(
            api_result(json!({"status": "success", "data": 3})).unwrap(),
            json!(3)
        );
        assert_eq!(parse_secret("secret_key = \" abc \"\n"), "abc");
        let (code, url) = new_claim();
        assert!(
            code.len() == 10 && code.bytes().all(|b| b.is_ascii_hexdigit()) && url.ends_with(&code)
        );
    }
}
