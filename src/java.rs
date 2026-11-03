//! Java : trouver ou télécharger le bon Java pour une version de Minecraft.
//! Port de app/core/java.py (même dossier runtimes/ que l'app Python).
use anyhow::{Context, Result, bail};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::time::{Duration, Instant};

use crate::{net, paths};

pub const JAVA_EXE: &str = if cfg!(windows) { "java.exe" } else { "java" };

/// Pas de fenêtre console noire pour java.exe (app sans console).
pub fn hide_window(cmd: &mut Command) -> &mut Command {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    cmd
}

/// Attend la fin du process ; au-delà de `timeout` il est tué (None).
pub fn wait_timeout(child: &mut Child, timeout: Duration) -> Option<ExitStatus> {
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Some(status),
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(50)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
        }
    }
}

/// Version majeure dans la sortie de `java -version` ("1.8.0_x" -> 8).
pub fn parse_major(output: &str) -> Option<u32> {
    let re = regex::Regex::new(r#"version "(\d+)(?:\.(\d+))?"#).ok()?;
    let c = re.captures(output)?;
    let major: u32 = c[1].parse().ok()?;
    match c.get(2) {
        Some(minor) if major == 1 => minor.as_str().parse().ok(),
        _ => Some(major),
    }
}

/// Version majeure de ce java, ou None s'il ne se lance pas.
fn check_java(java: &Path) -> Option<u32> {
    let mut child = hide_window(Command::new(java).arg("-version"))
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .ok()?;
    wait_timeout(&mut child, Duration::from_secs(15))?;
    let mut out = String::new();
    if let Some(mut e) = child.stderr.take() {
        let _ = e.read_to_string(&mut out);
    }
    if let Some(mut o) = child.stdout.take() {
        let _ = o.read_to_string(&mut out);
    }
    parse_major(&out)
}

/// Réglage « java_path » de data/settings.json (partagé avec l'app Python).
fn custom_java() -> Option<PathBuf> {
    let text = std::fs::read_to_string(paths::data_dir().join("settings.json")).ok()?;
    let v: serde_json::Value = serde_json::from_str(&text).ok()?;
    let p = v.get("java_path")?.as_str()?.trim();
    (!p.is_empty()).then(|| PathBuf::from(p))
}

fn sorted_dirs(dir: &Path) -> Vec<PathBuf> {
    let mut v: Vec<PathBuf> = std::fs::read_dir(dir)
        .map(|rd| {
            rd.flatten()
                .map(|e| e.path())
                .filter(|p| p.is_dir())
                .collect()
        })
        .unwrap_or_default();
    v.sort();
    v
}

/// Ordre de l'app Python : réglage, JAVA_HOME, PATH (le 1er, ou tous si
/// `all_path`), runtimes/ ; puis, sous Windows, Program Files\*\*.
fn candidates(all_path: bool) -> Vec<PathBuf> {
    let mut out: Vec<PathBuf> = custom_java().into_iter().collect();
    if let Some(home) = std::env::var_os("JAVA_HOME") {
        out.push(PathBuf::from(home).join("bin").join(JAVA_EXE));
    }
    if let Some(path) = std::env::var_os("PATH") {
        let in_path = std::env::split_paths(&path).map(|d| d.join(JAVA_EXE));
        if all_path {
            out.extend(in_path);
        } else {
            out.extend(in_path.filter(|p| p.is_file()).take(1)); // shutil.which
        }
    }
    let bin = |d: &PathBuf| d.join("bin").join(JAVA_EXE);
    out.extend(sorted_dirs(&paths::runtimes_dir()).iter().map(bin));
    if cfg!(windows) {
        // ex. C:\Program Files\Eclipse Adoptium\jre-21.0.4-hotspot\bin\java.exe
        if let Some(pf) = std::env::var_os("ProgramFiles") {
            for vendor in sorted_dirs(Path::new(&pf)) {
                out.extend(sorted_dirs(&vendor).iter().map(bin));
            }
        }
    }
    out
}

/// Premier Java utilisable (de version comprise dans `range` si donnée) :
/// (chemin, version majeure).
fn find_java(range: Option<(u32, u32)>) -> Option<(PathBuf, u32)> {
    let mut seen = std::collections::HashSet::new();
    for cand in candidates(range.is_some()) {
        let key = cand.to_string_lossy().to_string();
        let key = if cfg!(windows) {
            key.to_lowercase()
        } else {
            key
        };
        if !seen.insert(key) || !cand.is_file() {
            continue;
        }
        if let Some(major) = check_java(&cand)
            && range.is_none_or(|(lo, hi)| (lo..=hi).contains(&major))
        {
            return Some((cand, major));
        }
    }
    None
}

/// Java accepté pour une ancienne version ou un loader de version imposée :
/// les anciens Paper / Fabric / Forge ne tournent pas sous un Java récent.
pub fn pinned_java_range(mc_version: &str) -> (u32, u32) {
    match required_java_major(mc_version) {
        need if need <= 8 => (8, 8),
        16 => (16, 17),
        need => (need, need.max(21)),
    }
}

/// Version majeure de Java minimale selon la version de Minecraft.
pub fn required_java_major(mc_version: &str) -> u32 {
    let parts: Result<Vec<i64>, _> = mc_version.split('.').take(2).map(str::parse).collect();
    let Ok(parts) = parts else { return 21 };
    if parts[0] >= 26 {
        return 25; // nouveau schéma Mojang (26.1+)
    }
    if parts[0] != 1 || parts.len() < 2 {
        return 21;
    }
    match parts[1] {
        20 => {
            let patch: i64 = mc_version
                .split('.')
                .nth(2)
                .and_then(|p| p.parse().ok())
                .unwrap_or(0);
            if patch >= 5 { 21 } else { 17 }
        }
        m if m > 20 => 21,
        18 | 19 => 17,
        17 => 16, // Java 17 convient aussi
        _ => 8,
    }
}

/// (versions de Java acceptées, JRE à télécharger sinon). Bornées pour un
/// loader de version imposée et avant Java 21 ; None = tout Java ≥ JRE.
fn java_plan(mc_version: &str, pinned: bool) -> (Option<(u32, u32)>, u32) {
    let need = required_java_major(mc_version);
    if pinned || need < 21 {
        let (lo, hi) = pinned_java_range(mc_version);
        (Some((lo, hi)), if lo == 16 { 17 } else { lo }) // pas de JRE Temurin 16
    } else {
        (None, need)
    }
}

/// Chemin de `java` (java.exe sous Windows) adapté à `mc_version`,
/// téléchargé (Temurin) dans runtimes/ si aucun ne convient.
/// `pinned` : version de loader figée (voir PINNABLE côté Python).
pub fn ensure_java(mc_version: &str, pinned: bool, log: &dyn Fn(&str)) -> Result<PathBuf> {
    let (range, target) = java_plan(mc_version, pinned);
    if let Some((lo, hi)) = range {
        if let Some((found, major)) = find_java(range) {
            log(&format!(
                "Java détecté : {} (version {major})",
                found.display()
            ));
            return Ok(found);
        }
        log(&format!(
            "Cette version demande Java {lo} à {hi} (un Java plus récent la fait planter). \
             Téléchargement d'un JRE {target}…"
        ));
        return download_jre(target, log);
    }
    let need = target;
    match find_java(None) {
        Some((found, major)) if major >= need => {
            log(&format!(
                "Java détecté : {} (version {major})",
                found.display()
            ));
            return Ok(found);
        }
        Some((_, major)) => log(&format!(
            "Java {major} trouvé mais Minecraft {mc_version} requiert Java {need}+. \
             Téléchargement d'un JRE…"
        )),
        None => log("Aucun Java trouvé. Téléchargement d'un JRE Temurin…"),
    }
    download_jre(need, log)
}

/// JRE Temurin (API Adoptium) extrait dans runtimes/jre-{major}, comme
/// download_jre de l'app Python : les deux apps se le partagent.
pub fn download_jre(major: u32, log: &dyn Fn(&str)) -> Result<PathBuf> {
    let os = match std::env::consts::OS {
        "macos" => "mac",
        "linux" => "linux",
        _ => "windows",
    };
    let arch = if std::env::consts::ARCH == "aarch64" {
        "aarch64"
    } else {
        "x64"
    };
    let url = format!(
        "https://api.adoptium.net/v3/binary/latest/{major}/ga/{os}/{arch}/jre/hotspot/normal/eclipse"
    );
    let runtimes = paths::runtimes_dir();
    let dest = runtimes.join(format!("jre-{major}"));
    let java = dest.join("bin").join(JAVA_EXE);
    if java.is_file() {
        return Ok(java);
    }
    log(&format!("Téléchargement du JRE {major} ({os}/{arch})…"));
    let archive = runtimes.join(format!("jre-{major}.zip"));
    let tmp = runtimes.join(format!("_extract_{major}"));
    let res = net::download(&url, &archive, None)
        .context("Téléchargement de Java impossible")
        .and_then(|()| {
            log("Extraction du JRE…");
            unpack_jre(&archive, &tmp, &dest)
        });
    let _ = std::fs::remove_file(&archive);
    let _ = std::fs::remove_file(archive.with_extension("part"));
    let _ = std::fs::remove_dir_all(&tmp);
    res?;
    if !java.is_file() {
        bail!("JRE extrait mais binaire java introuvable.");
    }
    log(&format!("JRE {major} installé : {}", java.display()));
    Ok(java)
}

/// Extrait le zip dans `tmp` puis déplace son dossier racine
/// (« jdk-21.0.x+y-jre ») en `dest`.
fn unpack_jre(archive: &Path, tmp: &Path, dest: &Path) -> Result<()> {
    if tmp.exists() {
        std::fs::remove_dir_all(tmp)?;
    }
    // extract() assainit chaque chemin (comme enclosed_name) et refuse
    // l'archive si un chemin sort de tmp
    zip::ZipArchive::new(std::fs::File::open(archive)?)
        .and_then(|mut z| z.extract(tmp))
        .context("Archive Java illisible")?;
    let root = sorted_dirs(tmp)
        .into_iter()
        .next()
        .context("Archive Java vide")?;
    if dest.exists() {
        std::fs::remove_dir_all(dest)?;
    }
    std::fs::rename(root, dest)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn java_major_from_version_output() {
        assert_eq!(
            parse_major(r#"openjdk version "21.0.4" 2024-07-16"#),
            Some(21)
        );
        assert_eq!(parse_major(r#"java version "1.8.0_402""#), Some(8));
        assert_eq!(parse_major(r#"openjdk version "17" 2021-09-14"#), Some(17));
        assert_eq!(parse_major("pas de java ici"), None);
    }

    #[test]
    fn required_java_like_python() {
        for (mc, java) in [
            ("1.16.5", 8),
            ("1.17.1", 16),
            ("1.18.2", 17),
            ("1.20.4", 17),
            ("1.20.5", 21),
            ("1.21.4", 21),
            ("26.3", 25),
            ("n'importe", 21),
        ] {
            assert_eq!(required_java_major(mc), java, "{mc}");
        }
    }

    #[test]
    fn old_versions_get_a_java_they_can_run_on() {
        assert_eq!(pinned_java_range("1.12.2"), (8, 8));
        assert_eq!(pinned_java_range("1.16.5"), (8, 8));
        assert_eq!(pinned_java_range("1.17.1"), (16, 17));
        assert_eq!(pinned_java_range("1.20.1"), (17, 21));
        assert_eq!(pinned_java_range("1.21.4"), (21, 21));
        assert_eq!(pinned_java_range("26.3"), (25, 25));
        // Java cherché (borné ou non) et JRE téléchargé à défaut
        assert_eq!(java_plan("1.16.5", false), (Some((8, 8)), 8));
        assert_eq!(java_plan("1.21.4", false), (None, 21));
        assert_eq!(java_plan("1.17.1", false), (Some((16, 17)), 17)); // pas de JRE 16
        assert_eq!(java_plan("1.21.1", true), (Some((21, 21)), 21));
    }

    fn write_zip(path: &Path, entries: &[&str]) {
        use std::io::Write;
        let mut w = zip::ZipWriter::new(std::fs::File::create(path).unwrap());
        let o = zip::write::SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Stored);
        for e in entries {
            w.start_file(*e, o).unwrap();
            w.write_all(b"x").unwrap();
        }
        w.finish().unwrap();
    }

    #[test]
    fn jre_root_folder_becomes_runtimes_jre_n() {
        let dir = std::env::temp_dir().join(format!("sc-jre-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let (zip, tmp, dest) = (
            dir.join("jre-21.zip"),
            dir.join("_extract_21"),
            dir.join("jre-21"),
        );
        let java = format!("jdk-21.0.4+7-jre/bin/{JAVA_EXE}");
        write_zip(&zip, &[&java, "jdk-21.0.4+7-jre/release"]);
        unpack_jre(&zip, &tmp, &dest).unwrap();
        assert!(dest.join("bin").join(JAVA_EXE).is_file());
        // chemin qui sort du dossier : archive refusée, rien écrit dehors
        write_zip(&zip, &["jdk/../../evil.txt"]);
        assert!(unpack_jre(&zip, &tmp, &dir.join("jre-8")).is_err());
        assert!(!dir.join("evil.txt").exists() && !dir.parent().unwrap().join("evil.txt").exists());
        std::fs::remove_dir_all(dir).ok();
    }
}
