//! Commande de lancement d'un serveur (port de build_launch_command).
use anyhow::Result;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::java;
use crate::meta::{self, Meta};
use crate::props;

/// Sortie console Java en UTF-8 (sinon cp1252 sous Windows : accents cassés).
const ENC_FLAGS: [&str; 3] = [
    "-Dfile.encoding=UTF-8",
    "-Dstdout.encoding=UTF-8",
    "-Dstderr.encoding=UTF-8",
];
/// Loaders dont la version peut être imposée (`loader_version`).
const PINNABLE: [&str; 3] = ["fabric", "forge", "neoforge"];

/// (java, arguments). Télécharge Java si besoin : à appeler depuis un thread.
pub fn build_command(dir: &Path, m: &Meta, log: &dyn Fn(&str)) -> Result<(PathBuf, Vec<String>)> {
    let loader = meta::str_of(m, "loader");
    let pinned = !meta::str_of(m, "loader_version").is_empty() && PINNABLE.contains(&loader);
    let java = java::ensure_java(meta::str_of(m, "mc_version"), pinned, log)?;
    Ok((java, args_for(dir, m)?))
}

fn args_for(dir: &Path, m: &Meta) -> Result<Vec<String>> {
    let ram = meta::int_of(m, "ram_mb", 4096);
    let launch_args = meta::str_of(m, "launch_args");
    if !launch_args.is_empty() {
        // réplique run.bat : java @user_jvm_args.txt @…/win_args.txt nogui
        let jvm = format!("-Xms{ram}M\n-Xmx{ram}M\n{}\n", ENC_FLAGS.join("\n"));
        std::fs::write(dir.join("user_jvm_args.txt"), jvm)?;
        return Ok(vec![
            "@user_jvm_args.txt".into(),
            format!("@{launch_args}"),
            "nogui".into(),
        ]);
    }
    let jar = match meta::str_of(m, "jar") {
        "" => "server.jar",
        j => j,
    };
    let mut args = vec![format!("-Xms{ram}M"), format!("-Xmx{ram}M")];
    args.extend(ENC_FLAGS.iter().map(|s| s.to_string()));
    args.extend(["-jar".into(), jar.into(), "nogui".into()]);
    Ok(args)
}

/// Port du serveur : server.properties, sinon servercraft.json.
pub fn server_port(dir: &Path, m: &Meta) -> u16 {
    props::load(&dir.join("server.properties"))
        .get("server-port")
        .and_then(|p| props::parse_port(p))
        .unwrap_or(meta::int_of(m, "port", 25565) as u16)
}

/// Un programme répond déjà sur ce port ? (connexion locale seulement :
/// aucune écoute, donc pas de fenêtre du pare-feu Windows)
pub fn port_in_use(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn meta(v: serde_json::Value) -> Meta {
        v.as_object().unwrap().clone()
    }

    #[test]
    fn plain_jar_command() {
        let m = meta(json!({"ram_mb": 2048, "jar": "paper.jar"}));
        let args = args_for(Path::new("."), &m).unwrap();
        assert_eq!(args[..2], ["-Xms2048M", "-Xmx2048M"]);
        assert_eq!(args[args.len() - 3..], ["-jar", "paper.jar", "nogui"]);
    }

    #[test]
    fn forge_args_file_command() {
        let dir = std::env::temp_dir().join(format!("sc-launch-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let m = meta(json!({"ram_mb": "1024", "launch_args": "libraries/x/win_args.txt"}));
        let args = args_for(&dir, &m).unwrap();
        assert_eq!(args, ["@user_jvm_args.txt", "@libraries/x/win_args.txt", "nogui"]);
        let jvm = std::fs::read_to_string(dir.join("user_jvm_args.txt")).unwrap();
        assert!(jvm.starts_with("-Xms1024M\n-Xmx1024M\n-Dfile.encoding=UTF-8"));
        std::fs::remove_dir_all(dir).ok();
    }
}
