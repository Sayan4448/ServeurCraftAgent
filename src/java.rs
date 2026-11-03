//! Java : trouver ou télécharger le bon Java pour une version de Minecraft.
//! Port de app/core/java.py (même dossier runtimes/ que l'app Python).
use anyhow::Result;
use std::path::PathBuf;

/// Chemin de `java` (java.exe sous Windows) adapté à `mc_version`,
/// téléchargé (Temurin) dans runtimes/ si aucun ne convient.
/// `pinned` : version de loader figée (voir PINNABLE côté Python).
pub fn ensure_java(_mc_version: &str, _pinned: bool, _log: &dyn Fn(&str)) -> Result<PathBuf> {
    todo!("agent core")
}
