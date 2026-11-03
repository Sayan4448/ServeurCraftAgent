//! servercraft.json : métadonnées d'un serveur, même format que l'app
//! Python. On garde le JSON entier (Map) pour ne jamais perdre une clé que
//! seule la version Python connaît.
use anyhow::{Context, Result};
use serde_json::{Map, Value};
use std::path::{Path, PathBuf};

use crate::paths;

pub const META_FILE: &str = "servercraft.json";
pub type Meta = Map<String, Value>;

pub fn load(dir: &Path) -> Result<Meta> {
    let f = dir.join(META_FILE);
    let text = std::fs::read_to_string(&f).with_context(|| format!("{}", f.display()))?;
    match serde_json::from_str(&text)? {
        Value::Object(m) => Ok(m),
        _ => anyhow::bail!("{} : format inattendu", f.display()),
    }
}

pub fn save(dir: &Path, meta: &Meta) -> Result<()> {
    let text = serde_json::to_string_pretty(meta)?;
    std::fs::write(dir.join(META_FILE), text)?;
    Ok(())
}

pub fn str_of<'a>(m: &'a Meta, key: &str) -> &'a str {
    m.get(key).and_then(Value::as_str).unwrap_or("")
}

pub fn int_of(m: &Meta, key: &str, default: i64) -> i64 {
    match m.get(key) {
        Some(Value::Number(n)) => n.as_i64().unwrap_or(default),
        Some(Value::String(s)) => s.trim().parse().unwrap_or(default),
        _ => default,
    }
}

/// Nom de dossier d'un serveur (même règle que l'app Python).
pub fn slug(name: &str) -> String {
    let kept: String = name
        .chars()
        .filter(|c| c.is_alphanumeric() || *c == '_' || *c == '-' || *c == ' ')
        .collect();
    let s = kept.trim().replace(' ', "-").to_lowercase();
    if s.is_empty() { "serveur".into() } else { s }
}

#[derive(Clone, Debug)]
pub struct ServerInfo {
    pub name: String,
    pub dir: PathBuf,
    pub meta: Meta,
}

/// Serveurs valides (loader + version renseignés), triés par nom.
pub fn list_servers() -> Vec<ServerInfo> {
    let mut out = vec![];
    let Ok(rd) = std::fs::read_dir(paths::servers_dir()) else {
        return out;
    };
    let mut dirs: Vec<PathBuf> = rd.flatten().map(|e| e.path()).filter(|p| p.is_dir()).collect();
    dirs.sort();
    for d in dirs {
        let Ok(meta) = load(&d) else { continue };
        if str_of(&meta, "loader").is_empty() || str_of(&meta, "mc_version").is_empty() {
            continue;
        }
        let name = d.file_name().unwrap_or_default().to_string_lossy().to_string();
        out.push(ServerInfo { name, dir: d, meta });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slug_matches_python() {
        assert_eq!(slug("Mon Serveur!"), "mon-serveur");
        assert_eq!(slug("  ***  "), "serveur");
        assert_eq!(slug("Survie_2"), "survie_2");
    }

    #[test]
    fn save_keeps_unknown_keys() {
        let dir = std::env::temp_dir().join(format!("sc-meta-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join(META_FILE), r#"{"loader":"paper","scheduled_commands":[1]}"#).unwrap();
        let mut m = load(&dir).unwrap();
        m.insert("ram_mb".into(), 2048.into());
        save(&dir, &m).unwrap();
        let back = load(&dir).unwrap();
        assert_eq!(back["scheduled_commands"], serde_json::json!([1]));
        assert_eq!(int_of(&back, "ram_mb", 0), 2048);
        std::fs::remove_dir_all(dir).ok();
    }
}
