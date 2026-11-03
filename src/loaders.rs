//! Loaders (Paper, Purpur, Fabric, Forge, NeoForge, Mohist) : versions de
//! Minecraft disponibles et téléchargement. Port de app/core/downloader.py.
use anyhow::Result;

pub const LOADERS: &[(&str, &str)] = &[
    ("paper", "Paper (plugins)"),
    ("purpur", "Purpur (plugins)"),
    ("fabric", "Fabric (mods)"),
    ("forge", "Forge (mods)"),
    ("neoforge", "NeoForge (mods)"),
    ("mohist", "Mohist (mods + plugins)"),
];

/// Versions de Minecraft proposées pour `loader`, la plus récente d'abord.
pub fn versions(_loader: &str) -> Result<Vec<String>> {
    todo!("agent core")
}
