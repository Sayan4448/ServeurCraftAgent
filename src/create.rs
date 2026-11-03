//! Création d'un serveur. Port du cœur de create_server (app Python) :
//! dossier, jar du loader (+ installeur Forge/NeoForge), eula,
//! server.properties, servercraft.json au même format.
use anyhow::Result;
use std::path::PathBuf;

#[derive(Clone, Debug)]
pub struct CreateOptions {
    pub name: String,
    pub loader: String,
    pub mc_version: String,
    pub ram_mb: u32,
    pub port: u16,
    pub motd: String,
    pub online_mode: bool,
    pub playit_auto: bool,
}

/// Crée le serveur et retourne son dossier. Supprime le dossier en cas
/// d'échec. `progress(fait, total)` pour les téléchargements.
pub fn create_server(
    _opts: &CreateOptions,
    _log: &dyn Fn(&str),
    _progress: &dyn Fn(u64, u64),
) -> Result<PathBuf> {
    todo!("agent core")
}

/// Premier port ≥ 25565 qu'aucun serveur de la liste n'utilise.
pub fn free_port() -> u16 {
    todo!("agent core")
}
