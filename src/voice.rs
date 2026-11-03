//! Mods vocaux (Simple Voice Chat, Plasmo Voice) : détection, port UDP,
//! adresse publique du tunnel. Port des fonctions voice_* de
//! app/core/mods.py et de apply() de app/core/tunnels.py.
use anyhow::Result;
use regex::Regex;
use serde_json::Value;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use crate::playit::Tunnel;
use crate::props;

pub const DEFAULT_VOICE_PORT: u16 = 24454;
const PLUGIN_LOADERS: [&str; 3] = ["paper", "purpur", "mohist"]; // dossier plugins/
const MOD_LOADERS: [&str; 4] = ["fabric", "forge", "neoforge", "mohist"]; // dossier mods/

/// Noms des .jar actifs de mods/ puis plugins/ (selon le loader), triés :
/// list_installed() Python sans les .jar.disabled, que voice_mod ignore.
fn enabled_jars(dir: &Path, loader: &str) -> Vec<String> {
    let mut out = vec![];
    for (loaders, sub) in [(&MOD_LOADERS[..], "mods"), (&PLUGIN_LOADERS[..], "plugins")] {
        if !loaders.contains(&loader) {
            continue;
        }
        let Ok(rd) = std::fs::read_dir(dir.join(sub)) else {
            continue;
        };
        let mut names: Vec<String> = rd
            .flatten()
            .map(|e| e.file_name().to_string_lossy().to_string())
            .filter(|n| n.to_lowercase().ends_with(".jar"))
            .collect();
        names.sort();
        out.extend(names);
    }
    out
}

pub fn voicechat_config_path(dir: &Path, loader: &str) -> PathBuf {
    if PLUGIN_LOADERS.contains(&loader) && loader != "mohist" {
        return dir.join("plugins/voicechat/voicechat-server.properties");
    }
    dir.join("config/voicechat/voicechat-server.properties")
}

/// config.toml de Plasmo Voice 2.x (plugin Paper ou mod).
pub fn plasmo_config_path(dir: &Path, loader: &str) -> PathBuf {
    let plugin = dir.join("plugins/PlasmoVoice/config.toml");
    let module = dir.join("config/plasmovoice/server/config.toml");
    if plugin.exists() || module.exists() {
        return if plugin.exists() { plugin } else { module };
    }
    if loader == "paper" || loader == "purpur" {
        plugin
    } else {
        module
    }
}

/// Écrit port / voice_host dans voicechat-server.properties (lu par le mod
/// au démarrage), sans toucher aux autres lignes.
pub fn write_voicechat_config(dir: &Path, loader: &str, port: u16, host: &str) -> Result<PathBuf> {
    let path = voicechat_config_path(dir, loader);
    let current = props::load(&path);
    let mut changes = vec![
        ("port", port.to_string()),
        ("bind_address", String::new()),
        ("voice_host", host.to_string()),
    ];
    for (k, v) in [("allow_groups", "true"), ("max_voice_distance", "48")] {
        if !current.contains_key(k) {
            changes.push((k, v.to_string()));
        }
    }
    props::update(&path, &changes)?;
    Ok(path)
}

/// Mod vocal réellement présent : jar dans mods/ ou plugins/ (modpack,
/// gestionnaire de mods…), sinon sa config, sinon le choix de la création.
pub fn voice_mod(dir: &Path, loader: &str, chosen: &str) -> &'static str {
    for jar in enabled_jars(dir, loader) {
        let name: String = jar
            .to_lowercase()
            .chars()
            .filter(char::is_ascii_lowercase)
            .collect();
        if name.starts_with("voicechat") {
            return "simple_voice_chat";
        }
        if name.contains("plasmovoice") {
            return "plasmo_voice";
        }
    }
    if voicechat_config_path(dir, loader).exists() {
        return "simple_voice_chat";
    }
    if plasmo_config_path(dir, loader).exists() {
        return "plasmo_voice";
    }
    match chosen {
        "simple_voice_chat" => "simple_voice_chat",
        "plasmo_voice" => "plasmo_voice",
        _ => "none",
    }
}

/// Port UDP local du mod vocal. Simple Voice Chat : 24454 (-1 = port du
/// serveur) ; Plasmo Voice : celui du serveur ([host] port = 0).
pub fn voice_port(dir: &Path, loader: &str, voice: &str, server_port: u16) -> u16 {
    let (raw, default, same) = if voice == "plasmo_voice" {
        (
            toml_get(&plasmo_config_path(dir, loader), "host", "port"),
            0,
            0,
        )
    } else {
        let p = props::load(&voicechat_config_path(dir, loader)).remove("port");
        (p, i64::from(DEFAULT_VOICE_PORT), -1)
    };
    let port = match raw.as_deref().map(str::trim) {
        None | Some("") => default,
        Some(s) => s.parse().unwrap_or(default),
    };
    if port == same {
        return server_port;
    }
    u16::try_from(port)
        .ok()
        .filter(|p| *p > 0)
        .unwrap_or(DEFAULT_VOICE_PORT)
}

/// Adresse publique (tunnel UDP) annoncée aux joueurs par le mod vocal.
/// `address` vide = annoncer l'adresse du serveur (par défaut).
pub fn set_voice_host(
    dir: &Path,
    loader: &str,
    voice: &str,
    address: &str,
    port: u16,
) -> Result<PathBuf> {
    if voice != "plasmo_voice" {
        return write_voicechat_config(dir, loader, port, address);
    }
    let (host, public) = match address.rsplit_once(':') {
        Some((h, p)) if !h.is_empty() && !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit()) => {
            (h, p)
        }
        _ => (address, "0"),
    };
    let host = if host.is_empty() { "0.0.0.0" } else { host };
    let path = plasmo_config_path(dir, loader);
    // [host.public] ip 0.0.0.0 / port 0 = valeurs de [host] (comportement
    // par défaut de Plasmo Voice)
    toml_set(
        &path,
        "host.public",
        &[
            ("ip", serde_json::to_string(host)?),
            ("port", public.to_string()),
        ],
    )?;
    Ok(path)
}

static TOML_HEADER: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^\s*\[\[?\s*([^\[\]]+?)\s*\]\]?\s*(#.*)?$").expect("regex"));

/// (ligne d'en-tête, fin) de [section] ; None si absente (les en-têtes
/// commentés « # [host.public] » ne comptent pas).
fn toml_section(lines: &[String], section: &str) -> Option<(usize, usize)> {
    let mut start = None;
    for (i, line) in lines.iter().enumerate() {
        let Some(m) = TOML_HEADER.captures(line) else {
            continue;
        };
        if let Some(s) = start {
            return Some((s, i));
        }
        if &m[1] == section {
            start = Some(i);
        }
    }
    start.map(|s| (s, lines.len()))
}

fn toml_key(line: &str, key: &str) -> Option<String> {
    let re = Regex::new(&format!(
        r"^\s*{}\s*=\s*(.*?)\s*(#.*)?$",
        regex::escape(key)
    ))
    .ok()?;
    let m = re.captures(line)?;
    Some(m[1].trim_matches(|c| c == '"' || c == '\'').to_string())
}

fn toml_get(path: &Path, section: &str, key: &str) -> Option<String> {
    let text = std::fs::read_to_string(path).ok()?;
    let lines: Vec<String> = text.lines().map(str::to_string).collect();
    let (start, end) = toml_section(&lines, section)?;
    lines[start + 1..end].iter().find_map(|l| toml_key(l, key))
}

/// Remplace / ajoute des clés (valeurs TOML déjà formatées) dans une
/// section, sans toucher au reste du fichier ni à ses commentaires.
fn toml_set(path: &Path, section: &str, values: &[(&str, String)]) -> std::io::Result<()> {
    let mut lines: Vec<String> = match std::fs::read_to_string(path) {
        Ok(text) => text.lines().map(str::to_string).collect(),
        Err(_) => vec![
            "[host]".into(),
            "ip = \"0.0.0.0\"".into(),
            "port = 0".into(),
        ],
    };
    match toml_section(&lines, section) {
        None => {
            lines.push(String::new());
            lines.push(format!("[{section}]"));
            lines.extend(values.iter().map(|(k, v)| format!("{k} = {v}")));
        }
        Some((start, mut end)) => {
            for (key, val) in values {
                match (start + 1..end).find(|&j| toml_key(&lines[j], key).is_some()) {
                    Some(i) => lines[i] = format!("{key} = {val}"),
                    None => {
                        lines.insert(start + 1, format!("{key} = {val}"));
                        end += 1;
                    }
                }
            }
        }
    }
    if let Some(p) = path.parent() {
        std::fs::create_dir_all(p)?;
    }
    std::fs::write(path, lines.join("\n") + "\n")
}

/// int() Python sur une valeur JSON (nombre ou texte), 0 sinon.
fn int_of(v: &Value) -> i64 {
    match v {
        Value::Number(n) => n
            .as_i64()
            .or_else(|| n.as_f64().map(|f| f as i64))
            .unwrap_or(0),
        Value::String(s) => s.trim().parse().unwrap_or(0),
        _ => 0,
    }
}

/// Tunnels de servercraft.json (`tunnels`) valides : adresse renseignée,
/// proto tcp/udp, port local numérique (0 sinon).
pub fn clean(tunnels: &[Value]) -> Vec<Tunnel> {
    let mut out = vec![];
    for tn in tunnels {
        let address = tn["address"].as_str().unwrap_or("").trim();
        if address.is_empty() {
            continue;
        }
        let name = tn["name"].as_str().unwrap_or("").trim();
        out.push(Tunnel {
            name: if name.is_empty() { "Tunnel" } else { name }.to_string(),
            proto: if tn["proto"] == "udp" { "udp" } else { "tcp" }.to_string(),
            address: address.to_string(),
            local: u16::try_from(int_of(&tn["local"])).unwrap_or(0),
        });
    }
    out
}

/// Donne au mod vocal (Simple Voice Chat ou Plasmo Voice) l'adresse du
/// tunnel UDP qui vise son port, et écrit un récapitulatif
/// PLAYIT-README.txt. Retourne ce récapitulatif.
pub fn apply_tunnels(
    dir: &Path,
    loader: &str,
    tunnels: &[Value],
    java_port: u16,
    voice: &str,
) -> Result<String> {
    let tunnels = clean(tunnels);
    let voice = voice_mod(dir, loader, voice);
    if voice != "none" {
        let vport = voice_port(dir, loader, voice, java_port);
        if let Some(tn) = tunnels
            .iter()
            .find(|t| t.proto == "udp" && t.local == vport)
        {
            set_voice_host(dir, loader, voice, &tn.address, vport)?;
        }
    }
    let mut lines = vec!["=== Tunnels Playit.gg ===".to_string(), String::new()];
    for tn in &tunnels {
        let proto = tn.proto.to_uppercase();
        lines.push(format!(
            "{:<12} {proto:<4} {:<32} -> localhost:{}",
            tn.name, tn.address, tn.local
        ));
    }
    if tunnels.is_empty() {
        lines.push("(aucun tunnel)".into());
    }
    if let Some(java) = tunnels
        .iter()
        .find(|t| t.proto == "tcp" && t.local == java_port)
    {
        lines.push(String::new());
        lines.push(format!("Adresse : {}", java.address));
    }
    lines.push(String::new());
    lines.push(
        "Dans playit.gg, créez un tunnel par ligne (même protocole et même port local).".into(),
    );
    let summary = lines.join("\n");
    std::fs::write(dir.join("PLAYIT-README.txt"), &summary)?;
    Ok(summary)
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use serde_json::json;

    /// Dossier temporaire vide propre au test.
    pub fn temp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("sc-{name}-{}", std::process::id()));
        std::fs::remove_dir_all(&d).ok();
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn voice_chat_added_later_gets_its_voice_host() {
        let dir = temp("voice-svc");
        std::fs::create_dir_all(dir.join("mods")).unwrap();
        std::fs::write(dir.join("mods/voicechat-fabric-1.21.4-2.5.26.jar"), b"j").unwrap();
        std::fs::write(dir.join("mods/plasmovoice-fabric.jar.disabled"), b"j").unwrap();
        assert_eq!(voice_mod(&dir, "fabric", "none"), "simple_voice_chat");
        assert_eq!(
            voice_port(&dir, "fabric", "simple_voice_chat", 25565),
            24454
        );
        let tunnels = [
            json!({"name": "Bedrock", "proto": "udp", "address": "b.ply.gg:1", "local": 19132}),
            json!({"name": "Voice Chat", "proto": "udp", "address": "v.ply.gg:4242", "local": "24454"}),
        ];
        let summary = apply_tunnels(&dir, "fabric", &tunnels, 25565, "none").unwrap();
        let cfg = props::load(&dir.join("config/voicechat/voicechat-server.properties"));
        assert_eq!(cfg["voice_host"], "v.ply.gg:4242");
        assert_eq!(cfg["port"], "24454");
        assert!(summary.contains("Voice Chat   UDP  v.ply.gg:4242"));
        assert!(!summary.contains("Adresse :"));
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn plasmo_voice_host_goes_in_host_public() {
        let dir = temp("voice-plasmo");
        std::fs::create_dir_all(dir.join("plugins/PlasmoVoice")).unwrap();
        std::fs::write(dir.join("plugins/PlasmoVoice-Paper-2.1.3.jar"), b"j").unwrap();
        let cfg = dir.join("plugins/PlasmoVoice/config.toml");
        std::fs::write(
            &cfg,
            "config_version = \"1\"\n\n[host]\nip = \"0.0.0.0\"\nport = 0\n# [host.public]\n\
             # ip = \"127.0.0.1\"\n# port = 0\n\n[voice]\nsample_rate = 48000\n",
        )
        .unwrap();
        assert_eq!(voice_mod(&dir, "paper", "none"), "plasmo_voice");
        assert_eq!(voice_port(&dir, "paper", "plasmo_voice", 25570), 25570);
        let tunnels = [
            json!({"name": "Voice Chat", "proto": "udp", "address": "v.ply.gg:31337", "local": 25570}),
        ];
        for _ in 0..2 {
            // 2e passage : pas de doublon
            apply_tunnels(&dir, "paper", &tunnels, 25570, "plasmo_voice").unwrap();
        }
        let text = std::fs::read_to_string(&cfg).unwrap();
        assert_eq!(text.matches("[host.public]").count(), 2); // commenté + le vrai
        assert!(text.contains("\n[host.public]\nip = \"v.ply.gg\"\nport = 31337\n"));
        assert!(text.contains("sample_rate = 48000"));
        assert!(!dir.join("plugins/voicechat").exists());
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn clean_drops_empty_and_normalizes() {
        let t = clean(&[
            json!({"name": "", "proto": "x", "address": " a:1 ", "local": "7"}),
            json!({"name": "B", "proto": "udp", "address": ""}),
        ]);
        assert_eq!(
            t,
            vec![Tunnel {
                name: "Tunnel".into(),
                proto: "tcp".into(),
                address: "a:1".into(),
                local: 7
            }]
        );
    }
}
