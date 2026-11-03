//! Dossiers de données, partagés avec l'app Python : les deux voient les
//! mêmes serveurs (%LOCALAPPDATA%\ServerCraftAgent sous Windows).
use std::path::PathBuf;

pub fn app_dir() -> PathBuf {
    // tests et développement : dossier isolé
    if let Some(d) = std::env::var_os("SERVERCRAFT_HOME") {
        return PathBuf::from(d);
    }
    if cfg!(windows) {
        if let Some(d) = std::env::var_os("LOCALAPPDATA") {
            return PathBuf::from(d).join("ServerCraftAgent");
        }
    }
    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_default();
    home.join(".local/share/ServerCraftAgent")
}

pub fn servers_dir() -> PathBuf {
    app_dir().join("servers")
}

pub fn data_dir() -> PathBuf {
    app_dir().join("data")
}

pub fn runtimes_dir() -> PathBuf {
    app_dir().join("runtimes")
}

/// Hors des dossiers serveur : supprimer ou restaurer un serveur ne touche
/// pas à ses sauvegardes.
pub fn backups_dir() -> PathBuf {
    app_dir().join("backups")
}
