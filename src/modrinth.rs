//! Installation depuis Modrinth (port réduit de install_modrinth, app
//! Python) : version adaptée au loader et à Minecraft, release de
//! préférence, plugin chargeable par le Java du serveur, dépendances
//! obligatoires. Sert pour l'instant au plugin de mot de passe des comptes
//! crack ; le gestionnaire de mods viendra à l'étape suivante.
use anyhow::{Context, Result, bail};
use serde_json::{Value, json};
use std::collections::HashSet;
use std::io::Read;
use std::path::{Path, PathBuf};

use crate::{java, net};

const API: &str = "https://api.modrinth.com/v2";
/// Origine des fichiers installés (même fichier que l'app Python).
const MANIFEST: &str = ".servercraft-mods.json";

fn loaders_for(loader: &str, kind: &str) -> Vec<&'static str> {
    match (loader, kind) {
        ("mohist", "mod") => vec!["forge"],
        ("mohist", _) => vec!["bukkit", "paper", "spigot"],
        ("paper", _) => vec!["paper", "spigot", "bukkit"],
        ("purpur", _) => vec!["purpur", "paper", "spigot", "bukkit"],
        ("fabric", _) => vec!["fabric"],
        ("forge", _) => vec!["forge"],
        ("neoforge", _) => vec!["neoforge"],
        _ => vec![],
    }
}

fn versions(project: &str, loaders: &[&str], mc: &str) -> Result<Vec<Value>> {
    let url = format!(
        "{API}/project/{project}/version?loaders={}&game_versions={}",
        enc(&json!(loaders).to_string()),
        enc(&json!([mc]).to_string())
    );
    Ok(net::get_json(&url)?.as_array().cloned().unwrap_or_default())
}

/// Encodage d'URL des caractères de `["…"]`.
fn enc(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' | '.' | '~' => c.to_string(),
            c => c.to_string().bytes().map(|b| format!("%{b:02X}")).collect(),
        })
        .collect()
}

/// Releases d'abord, puis bêtas, puis alphas ; les plus récentes d'abord.
fn by_preference(mut v: Vec<Value>) -> Vec<Value> {
    let rank = |x: &Value| match x["version_type"].as_str() {
        Some("release") => 0,
        Some("beta") => 1,
        _ => 2,
    };
    v.sort_by(|a, b| {
        rank(a).cmp(&rank(b)).then_with(|| {
            b["date_published"]
                .as_str()
                .cmp(&a["date_published"].as_str())
        })
    });
    v
}

fn pick_jar(version: &Value) -> Option<(String, String)> {
    let files = version["files"].as_array()?;
    let f = files
        .iter()
        .find(|f| f["primary"].as_bool() == Some(true))
        .or_else(|| {
            files
                .iter()
                .find(|f| f["filename"].as_str().is_some_and(|n| n.ends_with(".jar")))
        })?;
    Some((
        f["url"].as_str()?.to_string(),
        f["filename"].as_str()?.to_string(),
    ))
}

/// Java le plus récent sous lequel tourne un serveur de cette version
/// (0 = pas de limite).
fn java_cap(mc: &str) -> u32 {
    if java::required_java_major(mc) >= 21 {
        0
    } else {
        java::pinned_java_range(mc).1
    }
}

/// Version de Java demandée par un plugin (classe principale de
/// plugin.yml), 0 si illisible.
fn plugin_java(jar: &Path) -> u32 {
    let read = || -> Option<u32> {
        let mut z = zip::ZipArchive::new(std::fs::File::open(jar).ok()?).ok()?;
        for meta in ["plugin.yml", "paper-plugin.yml"] {
            let Ok(mut f) = z.by_name(meta) else { continue };
            let mut text = String::new();
            f.read_to_string(&mut text).ok()?;
            drop(f);
            let main = text
                .lines()
                .find_map(|l| l.trim_start().strip_prefix("main:"))?
                .trim()
                .trim_matches(['"', '\'']);
            let mut cls = z
                .by_name(&format!("{}.class", main.replace('.', "/")))
                .ok()?;
            let mut head = [0u8; 8];
            cls.read_exact(&mut head).ok()?;
            return Some(u32::from(u16::from_be_bytes([head[6], head[7]])).saturating_sub(44));
        }
        None
    };
    read().unwrap_or(0)
}

fn record(server: &Path, dest: &Path, project: &str) {
    let f = server.join(MANIFEST);
    let mut data = std::fs::read_to_string(&f)
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        .filter(Value::is_object)
        .unwrap_or_else(|| json!({}));
    if let Ok(rel) = dest.strip_prefix(server) {
        let rel = rel.to_string_lossy().replace('\\', "/");
        data[rel] = json!({"source": "modrinth", "project": project});
        let _ = std::fs::write(&f, serde_json::to_string_pretty(&data).unwrap_or_default());
    }
}

/// Installe `project` et ses dépendances obligatoires dans mods/ ou plugins/.
pub fn install(
    server: &Path,
    loader: &str,
    mc: &str,
    project: &str,
    kind: &str,
    log: &dyn Fn(&str),
) -> Result<PathBuf> {
    install_inner(server, loader, mc, project, kind, log, &mut HashSet::new())
}

fn install_inner(
    server: &Path,
    loader: &str,
    mc: &str,
    project: &str,
    kind: &str,
    log: &dyn Fn(&str),
    seen: &mut HashSet<String>,
) -> Result<PathBuf> {
    let list = versions(project, &loaders_for(loader, kind), mc)?;
    if list.is_empty() {
        bail!("{project} : aucune version pour {loader} {mc}");
    }
    let pid = list[0]["project_id"]
        .as_str()
        .unwrap_or(project)
        .to_string();
    seen.insert(pid.clone());
    let folder = server.join(if kind == "plugin" { "plugins" } else { "mods" });
    // plugin : la version la plus récente que le Java du serveur sait charger
    let cap = if kind == "plugin" { java_cap(mc) } else { 0 };
    let mut chosen = None;
    for v in by_preference(list)
        .into_iter()
        .take(if cap > 0 { 6 } else { 1 })
    {
        let (url, file) =
            pick_jar(&v).with_context(|| format!("{project} : aucun fichier .jar"))?;
        let dest = folder.join(&file);
        net::download(&url, &dest, None)?;
        if cap == 0 || plugin_java(&dest) <= cap {
            chosen = Some((dest, v));
            break;
        }
        let _ = std::fs::remove_file(&dest);
    }
    let (dest, version) = chosen.with_context(|| {
        format!("{project} : aucune version ne fonctionne avec Java {cap} (Minecraft {mc})")
    })?;
    record(server, &dest, &pid);
    log(&format!(
        "  Installé : {}",
        dest.file_name().unwrap_or_default().to_string_lossy()
    ));
    let deps: Vec<String> = version["dependencies"]
        .as_array()
        .map(|d| {
            d.iter()
                .filter(|x| x["dependency_type"] == "required")
                .filter_map(|x| x["project_id"].as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    for dep in deps {
        if seen.contains(&dep) {
            continue;
        }
        if let Err(e) = install_inner(server, loader, mc, &dep, kind, log, seen) {
            // le mod seul ferait planter le serveur
            let _ = std::fs::remove_file(&dest);
            return Err(e.context(format!("dépendance obligatoire de {project} introuvable")));
        }
    }
    Ok(dest)
}

/// Mot de passe pour les comptes crack : AuthMe (plugins) ou EasyAuth
/// (Fabric). Non bloquant : un échec est signalé dans le journal.
pub fn install_auth(server: &Path, loader: &str, mc: &str, log: &dyn Fn(&str)) {
    let (project, kind, label) = if crate::loaders::PLUGIN_LOADERS.contains(&loader) {
        ("authmereloaded", "plugin", "AuthMe")
    } else if loader == "fabric" {
        ("easyauth", "mod", "EasyAuth")
    } else {
        log(
            "  ⚠ Aucun plugin de mot de passe disponible pour ce loader : les joueurs crack peuvent prendre n'importe quel pseudo.",
        );
        return;
    };
    log(&format!(
        "Sécurité : installation d'{label} (mot de passe des comptes crack)…"
    ));
    if let Err(e) = install(server, loader, mc, project, kind, log) {
        log(&format!("  ⚠ {label} non installé : {e:#}"));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn release_preferred_then_newest() {
        let v = vec![
            json!({"id": "beta-new", "version_type": "beta", "date_published": "2026-05-01"}),
            json!({"id": "rel-old", "version_type": "release", "date_published": "2025-01-01"}),
            json!({"id": "rel-new", "version_type": "release", "date_published": "2026-01-01"}),
        ];
        let ids: Vec<_> = by_preference(v)
            .iter()
            .map(|x| x["id"].as_str().unwrap().to_string())
            .collect();
        assert_eq!(ids, ["rel-new", "rel-old", "beta-new"]);
    }

    #[test]
    fn query_is_url_encoded() {
        assert_eq!(
            enc(r#"["paper","bukkit"]"#),
            "%5B%22paper%22%2C%22bukkit%22%5D"
        );
        assert_eq!(
            loaders_for("mohist", "plugin"),
            ["bukkit", "paper", "spigot"]
        );
    }

    #[test]
    fn plugin_java_from_class_file() {
        let dir = std::env::temp_dir().join(format!("sc-mr-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let jar = dir.join("p.jar");
        let mut z = zip::ZipWriter::new(std::fs::File::create(&jar).unwrap());
        let o = zip::write::SimpleFileOptions::default();
        use std::io::Write;
        z.start_file("plugin.yml", o).unwrap();
        z.write_all(b"name: P\nmain: fr.test.Main\n").unwrap();
        z.start_file("fr/test/Main.class", o).unwrap();
        z.write_all(&[0xCA, 0xFE, 0xBA, 0xBE, 0, 0, 0, 61]).unwrap(); // Java 17
        z.finish().unwrap();
        assert_eq!(plugin_java(&jar), 17);
        assert_eq!(java_cap("1.16.5"), 8);
        std::fs::remove_dir_all(dir).ok();
    }
}
