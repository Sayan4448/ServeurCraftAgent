//! Sauvegardes des mondes (port de app/core/backups.py, même format) :
//! `backups/<serveur>/AAAA-MM-JJ_HH-MM-SS_<raison>.zip`.
//!
//! Serveur lancé : `save-off`, `save-all flush` (on attend « Saved the
//! game »), zip, puis `save-on` : le monde ne bouge pas pendant la copie.
//! Rotation : seules les sauvegardes automatiques au-delà de `keep` sont
//! supprimées ; les manuelles sont gardées.
use anyhow::{Context, Result, bail};
use regex::Regex;
use std::collections::HashSet;
use std::io::Write;
use std::path::{Component, Path, PathBuf};
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant, SystemTime};
use zip::write::SimpleFileOptions;

use crate::paths;
use crate::process::ServerProcess;
use crate::props;

pub const DEFAULT_KEEP: i64 = 10;
const ROTATED: [&str; 4] = ["auto", "stop", "restart", "restore"];
const SKIP: [&str; 1] = ["session.lock"];

static NAME: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(\d{4}-\d\d-\d\d)_(\d\d)-(\d\d)-(\d\d)(?:-\d+)?_(\w+)\.zip$").unwrap()
});
static SAVED: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"Saved the (game|world)").unwrap());
/// Serveurs dont une sauvegarde est en cours.
static BUSY: LazyLock<Mutex<HashSet<String>>> = LazyLock::new(Default::default);

#[derive(Clone, Debug)]
pub struct Backup {
    pub path: PathBuf,
    pub date: String,
    pub reason: String,
    pub size: u64,
    mtime: SystemTime,
}

pub fn backup_dir(name: &str) -> PathBuf {
    paths::backups_dir().join(name)
}

pub fn reason_label(reason: &str) -> &'static str {
    match reason {
        "manual" => "Manuelle",
        "auto" => "Automatique",
        "stop" => "Avant arrêt",
        "restart" => "Avant redémarrage",
        "restore" => "Avant restauration",
        _ => "Autre",
    }
}

pub fn fmt_size(n: u64) -> String {
    let mut v = n as f64;
    for unit in ["o", "Ko", "Mo"] {
        if v < 1024.0 {
            return if unit == "o" {
                format!("{v:.0} {unit}")
            } else {
                format!("{v:.1} {unit}")
            };
        }
        v /= 1024.0;
    }
    format!("{v:.1} Go")
}

/// <level>, <level>_nether, <level>_the_end (Paper les sépare, Fabric et
/// Forge rangent tout dans <level>).
pub fn world_dirs(server: &Path) -> Vec<PathBuf> {
    let p = props::load(&server.join("server.properties"));
    let level = p
        .get("level-name")
        .filter(|s| !s.is_empty())
        .map_or("world", |s| s.as_str());
    [
        level.to_string(),
        format!("{level}_nether"),
        format!("{level}_the_end"),
    ]
    .iter()
    .map(|n| server.join(n))
    .filter(|d| d.is_dir())
    .collect()
}

pub fn busy(name: &str) -> bool {
    BUSY.lock().unwrap().contains(name)
}

/// Plus récentes d'abord.
pub fn list(name: &str) -> Vec<Backup> {
    list_in(&backup_dir(name))
}

fn list_in(dir: &Path) -> Vec<Backup> {
    let Ok(rd) = std::fs::read_dir(dir) else {
        return vec![];
    };
    let mut out: Vec<Backup> = rd
        .flatten()
        .filter_map(|e| {
            let path = e.path();
            let file = path.file_name()?.to_str()?.to_string();
            if !file.ends_with(".zip") {
                return None;
            }
            let md = e.metadata().ok()?;
            let mtime = md.modified().unwrap_or(SystemTime::UNIX_EPOCH);
            let (date, reason) = match NAME.captures(&file) {
                Some(c) => (
                    format!("{} {}:{}:{}", &c[1], &c[2], &c[3], &c[4]),
                    c[5].to_string(),
                ),
                None => {
                    let dt: chrono::DateTime<chrono::Local> = mtime.into();
                    (dt.format("%Y-%m-%d %H:%M:%S").to_string(), "other".into())
                }
            };
            Some(Backup {
                path,
                date,
                reason,
                size: md.len(),
                mtime,
            })
        })
        .collect();
    out.sort_by(|a, b| (&b.date, b.mtime).cmp(&(&a.date, a.mtime)));
    out
}

/// Supprime les sauvegardes automatiques au-delà des `keep` plus récentes.
fn rotate_in(dir: &Path, keep: i64) -> usize {
    let keep = keep.max(1) as usize;
    list_in(dir)
        .into_iter()
        .filter(|b| ROTATED.contains(&b.reason.as_str()))
        .skip(keep)
        .filter(|b| std::fs::remove_file(&b.path).is_ok())
        .count()
}

fn zip_world(dest: &Path, server: &Path, dirs: &[PathBuf], reason: &str) -> Result<PathBuf> {
    std::fs::create_dir_all(dest)?;
    let stamp = chrono::Local::now().format("%Y-%m-%d_%H-%M-%S").to_string();
    let mut fin = dest.join(format!("{stamp}_{reason}.zip"));
    let mut i = 1;
    while fin.exists() {
        fin = dest.join(format!("{stamp}-{i}_{reason}.zip"));
        i += 1;
    }
    let part = fin.with_extension("zip.part");
    let res = (|| -> Result<()> {
        let mut z = zip::ZipWriter::new(std::fs::File::create(&part)?);
        let opts = SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Deflated)
            .compression_level(Some(6))
            .large_file(true);
        for d in dirs {
            let mut files = vec![];
            walk(d, &mut files);
            files.sort();
            for f in files {
                if f.file_name()
                    .and_then(|n| n.to_str())
                    .is_some_and(|n| SKIP.contains(&n))
                {
                    continue;
                }
                let Ok(rel) = f.strip_prefix(server) else {
                    continue;
                };
                let rel = rel.to_string_lossy().replace('\\', "/");
                // fichier verrouillé par Java : on passe
                let Ok(data) = std::fs::read(&f) else {
                    continue;
                };
                z.start_file(rel, opts)?;
                z.write_all(&data)?;
            }
        }
        z.finish()?;
        Ok(())
    })();
    if let Err(e) = res {
        let _ = std::fs::remove_file(&part);
        return Err(e);
    }
    std::fs::rename(&part, &fin)?;
    Ok(fin)
}

fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(rd) = std::fs::read_dir(dir) else {
        return;
    };
    for e in rd.flatten() {
        let p = e.path();
        match e.file_type() {
            Ok(t) if t.is_dir() => walk(&p, out),
            Ok(t) if t.is_file() => out.push(p),
            _ => {}
        }
    }
}

/// Zippe le monde. `proc` lancé et prêt : save-off / save-all / save-on.
pub fn create(
    name: &str,
    server: &Path,
    reason: &str,
    keep: i64,
    proc: Option<&ServerProcess>,
    log: &dyn Fn(&str),
) -> Result<PathBuf> {
    if !BUSY.lock().unwrap().insert(name.to_string()) {
        bail!("Une sauvegarde de ce serveur est déjà en cours.");
    }
    let res = (|| {
        let dirs = world_dirs(server);
        if dirs.is_empty() {
            bail!("Aucun monde à sauvegarder (le serveur n'a jamais été lancé ?).");
        }
        log(&format!(
            "── Sauvegarde du monde ({})… ──",
            reason_label(reason).to_lowercase()
        ));
        let t0 = Instant::now();
        let live = proc.filter(|p| p.status().ready);
        if let Some(p) = live {
            p.send("save-off");
            let (_, seen) = p.lines_since(u64::MAX);
            p.send("save-all flush");
            wait_saved(p, seen, Duration::from_secs(60));
        }
        let zipped = zip_world(&backup_dir(name), server, &dirs, reason);
        if let Some(p) = live {
            p.send("save-on");
        }
        let path = zipped?;
        rotate_in(&backup_dir(name), keep);
        let size = std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0);
        log(&format!(
            "── Sauvegarde terminée : {} ({}, {} s) ──",
            path.file_name().unwrap_or_default().to_string_lossy(),
            fmt_size(size),
            t0.elapsed().as_secs()
        ));
        Ok(path)
    })();
    BUSY.lock().unwrap().remove(name);
    res
}

fn wait_saved(p: &ServerProcess, mut seen: u64, timeout: Duration) {
    let end = Instant::now() + timeout;
    while Instant::now() < end && p.is_running() {
        let (lines, s) = p.lines_since(seen);
        seen = s;
        if lines.iter().any(|l| SAVED.is_match(l)) {
            return;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
}

fn safe(rel: &Path) -> bool {
    rel.components().next().is_some() && rel.components().all(|c| matches!(c, Component::Normal(_)))
}

/// Remplace le monde par le zip (serveur arrêté). Le monde actuel est
/// d'abord sauvegardé (raison « restore »).
pub fn restore(
    name: &str,
    server: &Path,
    zip_path: &Path,
    keep: i64,
    log: &dyn Fn(&str),
) -> Result<()> {
    let f = std::fs::File::open(zip_path).context("sauvegarde introuvable")?;
    let mut z = zip::ZipArchive::new(f).context("sauvegarde illisible")?;
    let mut members = vec![];
    for i in 0..z.len() {
        let e = z.by_index(i)?;
        if let Some(p) = e.enclosed_name().filter(|p| safe(p)) {
            members.push((i, p, e.is_dir()));
        }
    }
    let mut tops: Vec<_> = members
        .iter()
        .filter_map(|(_, p, _)| p.components().next().map(|c| c.as_os_str().to_owned()))
        .collect();
    tops.sort();
    tops.dedup();
    if tops.is_empty() {
        bail!("Cette sauvegarde ne contient aucun monde.");
    }
    if !world_dirs(server).is_empty() {
        create(name, server, "restore", keep, None, log)?;
    }
    for top in &tops {
        let target = server.join(top);
        if target.is_dir() {
            std::fs::remove_dir_all(&target)?;
        }
    }
    for (i, rel, is_dir) in members {
        let out = server.join(&rel);
        if is_dir {
            std::fs::create_dir_all(&out)?;
            continue;
        }
        if let Some(p) = out.parent() {
            std::fs::create_dir_all(p)?;
        }
        let mut e = z.by_index(i)?;
        let mut dst = std::fs::File::create(&out)?;
        std::io::copy(&mut e, &mut dst)?;
    }
    log("── Monde restauré ──");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("sc-bk-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn zip_list_rotate() {
        let root = tmp("zip");
        let server = root.join("srv");
        std::fs::create_dir_all(server.join("world/region")).unwrap();
        std::fs::create_dir_all(server.join("world_nether")).unwrap();
        std::fs::write(server.join("world/level.dat"), b"monde").unwrap();
        std::fs::write(server.join("world/session.lock"), b"x").unwrap();
        std::fs::write(server.join("world_nether/n.dat"), b"n").unwrap();
        let dirs = world_dirs(&server);
        assert_eq!(dirs.len(), 2);
        let dest = root.join("backups");
        let a = zip_world(&dest, &server, &dirs, "manual").unwrap();
        for _ in 0..3 {
            zip_world(&dest, &server, &dirs, "auto").unwrap();
        }
        let mut z = zip::ZipArchive::new(std::fs::File::open(&a).unwrap()).unwrap();
        let names: Vec<String> = (0..z.len())
            .map(|i| z.by_index(i).unwrap().name().unwrap().to_string())
            .collect();
        assert_eq!(names, ["world/level.dat", "world_nether/n.dat"]);
        assert_eq!(list_in(&dest).len(), 4);
        assert_eq!(rotate_in(&dest, 1), 2); // 3 auto → 1, la manuelle reste
        let left = list_in(&dest);
        assert_eq!(left.iter().filter(|b| b.reason == "manual").count(), 1);
        assert_eq!(left.len(), 2);
        std::fs::remove_dir_all(root).ok();
    }

    #[test]
    fn restore_into_a_server_without_world() {
        let root = tmp("restore");
        let a = root.join("a");
        std::fs::create_dir_all(a.join("world/region")).unwrap();
        std::fs::write(a.join("world/region/r.0.0.mca"), b"chunks").unwrap();
        let zip = zip_world(&root.join("bk"), &a, &world_dirs(&a), "manual").unwrap();
        let b = root.join("b");
        std::fs::create_dir_all(&b).unwrap();
        restore("b", &b, &zip, 10, &|_| {}).unwrap();
        assert_eq!(
            std::fs::read(b.join("world/region/r.0.0.mca")).unwrap(),
            b"chunks"
        );
        std::fs::remove_dir_all(root).ok();
    }

    #[test]
    fn name_format_matches_python() {
        let c = NAME.captures("2026-11-03_14-05-09-1_stop.zip").unwrap();
        assert_eq!((&c[1], &c[5]), ("2026-11-03", "stop"));
        assert_eq!(fmt_size(512), "512 o");
        assert_eq!(fmt_size(1536 * 1024), "1.5 Mo");
    }

    #[test]
    fn unsafe_paths_are_refused() {
        assert!(safe(Path::new("world/level.dat")));
        assert!(!safe(Path::new("../evil")));
        assert!(!safe(Path::new("/abs")));
    }
}
