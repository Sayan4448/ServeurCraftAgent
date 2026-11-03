//! Loaders (Paper, Purpur, Fabric, Forge, NeoForge, Mohist) : versions de
//! Minecraft disponibles et téléchargement. Port de app/core/downloader.py.
use anyhow::{Context, Result, bail};
use serde_json::Value;

use crate::net;

pub const LOADERS: &[(&str, &str)] = &[
    ("paper", "Paper (plugins)"),
    ("purpur", "Purpur (plugins)"),
    ("fabric", "Fabric (mods)"),
    ("forge", "Forge (mods)"),
    ("neoforge", "NeoForge (mods)"),
    ("mohist", "Mohist (mods + plugins)"),
];

/// Loaders qui ont un dossier plugins/ ou mods/.
pub const PLUGIN_LOADERS: &[&str] = &["paper", "purpur", "mohist"];
pub const MOD_LOADERS: &[&str] = &["fabric", "forge", "neoforge", "mohist"];
/// Loaders dont la version peut être imposée (modpacks).
pub const PINNABLE: &[&str] = &["fabric", "forge", "neoforge"];

const PAPER_API: &str = "https://fill.papermc.io/v3/projects/paper";
const PURPUR_API: &str = "https://api.purpurmc.org/v2/purpur";
const FABRIC_META: &str = "https://meta.fabricmc.net/v2/versions";
const FORGE_PROMOS: &str =
    "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json";
const FORGE_MAVEN: &str = "https://maven.minecraftforge.net/net/minecraftforge/forge";
const NEOFORGE_META: &str =
    "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml";
const NEOFORGE_MAVEN: &str = "https://maven.neoforged.net/releases/net/neoforged/neoforge";
const MOHIST_API: &str = "https://api.mohistmc.com/project/mohist";

/// Versions de Minecraft proposées pour `loader`, la plus récente d'abord.
pub fn versions(loader: &str) -> Result<Vec<String>> {
    Ok(match loader {
        "paper" => {
            let all: Vec<String> = net::get_json(PAPER_API)?["versions"]
                .as_object()
                .map(|groups| groups.values().flat_map(strings).collect())
                .unwrap_or_default();
            let stable: Vec<String> = all.iter().filter(|v| !v.contains('-')).cloned().collect();
            // serde_json range les groupes par clé : on retrie (rc/pre exclues)
            sort_mc_versions(if stable.is_empty() { all } else { stable })
        }
        "purpur" => {
            let mut v = strings(&net::get_json(PURPUR_API)?["versions"]);
            v.reverse();
            v
        }
        "fabric" => net::get_json(&format!("{FABRIC_META}/game"))?
            .as_array()
            .map(|a| {
                a.iter()
                    .filter(|v| v["stable"].as_bool() == Some(true))
                    .filter_map(|v| v["version"].as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default(),
        "forge" => {
            let promos = net::get_json(FORGE_PROMOS)?;
            let mcs = promos["promos"]
                .as_object()
                .into_iter()
                .flat_map(|p| p.keys())
                .filter_map(|k| {
                    let (mc, kind) = k.rsplit_once('-')?;
                    (!mc.is_empty() && (kind == "latest" || kind == "recommended"))
                        .then(|| mc.to_string())
                });
            sort_mc_versions(mcs.collect::<std::collections::BTreeSet<_>>())
        }
        "neoforge" => {
            let xml = net::get_text(NEOFORGE_META)?;
            let mcs = maven_versions(&xml)
                .into_iter()
                .filter_map(|v| neoforge_to_mc(&v));
            sort_mc_versions(mcs.collect::<std::collections::BTreeSet<_>>())
        }
        "mohist" => {
            let data = net::get_json(&format!("{MOHIST_API}/versions"))?;
            let names = data.as_array().into_iter().flatten();
            sort_mc_versions(names.filter_map(|v| v["name"].as_str().map(String::from)))
        }
        _ => bail!("Loader inconnu : {loader}"),
    })
}

/// Ce que la création doit télécharger : le jar du serveur, ou l'installeur
/// Forge/NeoForge à lancer avec --installServer.
#[derive(Clone, Debug, PartialEq)]
pub struct Download {
    pub url: String,
    pub filename: String,
    pub installer: bool,
}

/// Port de get_download. `loader_version` (modpacks) : version exacte de
/// Fabric/Forge/NeoForge, ignorée pour les autres loaders.
pub fn get_download(loader: &str, mc: &str, loader_version: Option<&str>) -> Result<Download> {
    let pin = loader_version
        .filter(|_| PINNABLE.contains(&loader))
        .map(String::from);
    let jar = |url: String, filename: String| Download {
        url,
        filename,
        installer: false,
    };
    let installer = |url: String, filename: String| Download {
        url,
        filename,
        installer: true,
    };
    Ok(match loader {
        "paper" => {
            let build = net::get_json(&format!("{PAPER_API}/versions/{mc}/builds/latest"))?;
            jar(
                text_at(&build, "/downloads/server:default/url")?,
                text_at(&build, "/downloads/server:default/name")?,
            )
        }
        "purpur" => jar(
            format!("{PURPUR_API}/{mc}/latest/download"),
            format!("purpur-{mc}.jar"),
        ),
        "fabric" => {
            let loader_ver = match pin {
                Some(v) => v,
                None => text_at(
                    &net::get_json(&format!("{FABRIC_META}/loader/{mc}"))?,
                    "/0/loader/version",
                )
                .with_context(|| format!("Aucun loader Fabric pour {mc}"))?,
            };
            let inst = text_at(
                &net::get_json(&format!("{FABRIC_META}/installer"))?,
                "/0/version",
            )?;
            jar(
                format!("{FABRIC_META}/loader/{mc}/{loader_ver}/{inst}/server/jar"),
                format!("fabric-server-{mc}.jar"),
            )
        }
        "forge" => {
            let forge_ver = match pin {
                Some(v) => v,
                None => {
                    let promos = net::get_json(FORGE_PROMOS)?;
                    [format!("{mc}-recommended"), format!("{mc}-latest")]
                        .iter()
                        .find_map(|k| promos["promos"][k].as_str().map(String::from))
                        .with_context(|| format!("Aucun build Forge pour {mc}"))?
                }
            };
            let filename = format!("forge-{mc}-{forge_ver}-installer.jar");
            installer(
                format!("{FORGE_MAVEN}/{mc}-{forge_ver}/{filename}"),
                filename,
            )
        }
        "neoforge" => {
            let best = match pin {
                Some(v) => v,
                None => neoforge_best(&net::get_text(NEOFORGE_META)?, mc)
                    .with_context(|| format!("Aucun build NeoForge pour {mc}"))?,
            };
            let filename = format!("neoforge-{best}-installer.jar");
            installer(format!("{NEOFORGE_MAVEN}/{best}/{filename}"), filename)
        }
        "mohist" => {
            let id = text_at(
                &net::get_json(&format!("{MOHIST_API}/{mc}/builds/latest"))?,
                "/id",
            )?;
            jar(
                format!("{MOHIST_API}/{mc}/builds/{id}/download"),
                format!("mohist-{mc}-{id}.jar"),
            )
        }
        _ => bail!("Loader inconnu : {loader}"),
    })
}

fn strings(v: &Value) -> Vec<String> {
    v.as_array()
        .map(|a| {
            a.iter()
                .filter_map(|s| s.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default()
}

fn text_at(v: &Value, pointer: &str) -> Result<String> {
    match v.pointer(pointer) {
        Some(Value::String(s)) => Ok(s.clone()),
        Some(Value::Number(n)) => Ok(n.to_string()),
        _ => bail!("Réponse inattendue du site de téléchargement ({pointer})."),
    }
}

/// Tri « 1.21.10 > 1.21.9 > 1.21 » (parties non numériques = -1), du plus
/// récent au plus ancien, comme _sort_mc_versions.
pub fn sort_mc_versions(versions: impl IntoIterator<Item = String>) -> Vec<String> {
    let key = |v: &str| -> Vec<i64> {
        v.split('.')
            .map(|p| match p.bytes().all(|b| b.is_ascii_digit()) {
                true => p.parse().unwrap_or(-1),
                false => -1,
            })
            .collect()
    };
    let mut out: Vec<String> = versions.into_iter().collect();
    out.sort_by_key(|v| std::cmp::Reverse(key(v)));
    out
}

/// Contenu des balises <version> d'un maven-metadata.xml, dans l'ordre.
fn maven_versions(xml: &str) -> Vec<String> {
    let Ok(re) = regex::Regex::new(r"<version>([^<]*)</version>") else {
        return vec![];
    };
    re.captures_iter(xml)
        .map(|c| c[1].trim().to_string())
        .collect()
}

/// NeoForge -> version MC. Ancien schéma : 21.1.x -> 1.21.1, 21.0.x -> 1.21 ;
/// nouveau (Mojang 2026) : 26.1.2.x -> 26.1.2, 26.2.0.x -> 26.2.
fn neoforge_to_mc(ver: &str) -> Option<String> {
    let base = ver.split('-').next()?.split('+').next()?;
    let parts: Vec<&str> = base.split('.').collect();
    let digits = |p: &str| !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit());
    if parts.len() == 3 && digits(parts[0]) {
        let (major, minor) = (parts[0], parts[1]);
        return Some(if minor != "0" {
            format!("1.{major}.{minor}")
        } else {
            format!("1.{major}")
        });
    }
    if parts.len() >= 4 && parts[..3].iter().all(|p| digits(p)) {
        let (y, d, p) = (parts[0], parts[1], parts[2]);
        return Some(if p != "0" {
            format!("{y}.{d}.{p}")
        } else {
            format!("{y}.{d}")
        });
    }
    None
}

/// 1.21.1 -> 21.1 ; 1.21 -> 21.0 ; 26.1.2 -> 26.1.2 ; 26.2 -> 26.2.0
fn mc_to_neoforge_prefix(mc: &str) -> String {
    let parts: Vec<&str> = mc.split('.').collect();
    let at = |i: usize| parts.get(i).copied().unwrap_or("0");
    if parts[0] == "1" {
        return if parts.len() >= 3 {
            format!("{}.{}", at(1), at(2))
        } else {
            format!("{}.0", at(1))
        };
    }
    if parts.len() >= 3 {
        parts[..3].join(".")
    } else {
        format!("{}.{}.0", at(0), at(1))
    }
}

/// Dernier build NeoForge de la liste maven pour cette version de MC.
fn neoforge_best(xml: &str, mc: &str) -> Option<String> {
    let prefix = mc_to_neoforge_prefix(mc) + ".";
    maven_versions(xml)
        .into_iter()
        .rfind(|v| v.split('-').next().unwrap_or("").starts_with(&prefix))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(v: &[&str]) -> Vec<String> {
        v.iter().map(|x| x.to_string()).collect()
    }

    #[test]
    fn versions_sorted_newest_first() {
        let got = sort_mc_versions(s(&[
            "1.20.1", "1.21", "1.8.9", "26.1", "1.21.10", "1.21.9", "1.21.1",
        ]));
        assert_eq!(
            got,
            s(&[
                "26.1", "1.21.10", "1.21.9", "1.21.1", "1.21", "1.20.1", "1.8.9"
            ])
        );
        // partie non numérique = -1 : passe derrière la version sans suffixe
        assert_eq!(
            sort_mc_versions(s(&["1.21-rc1", "1.21"])),
            s(&["1.21", "1.21-rc1"])
        );
    }

    #[test]
    fn neoforge_versions_map_to_minecraft() {
        assert_eq!(neoforge_to_mc("21.1.77").as_deref(), Some("1.21.1"));
        assert_eq!(neoforge_to_mc("21.0.167").as_deref(), Some("1.21"));
        assert_eq!(neoforge_to_mc("20.4.80-beta").as_deref(), Some("1.20.4"));
        assert_eq!(neoforge_to_mc("26.1.2.126").as_deref(), Some("26.1.2"));
        assert_eq!(neoforge_to_mc("26.2.0.3-beta").as_deref(), Some("26.2"));
        assert_eq!(
            neoforge_to_mc("26.1.0.0-alpha.1+snapshot-1").as_deref(),
            Some("26.1")
        );
        assert_eq!(neoforge_to_mc("bizarre"), None);
        assert_eq!(mc_to_neoforge_prefix("1.21.1"), "21.1");
        assert_eq!(mc_to_neoforge_prefix("1.21"), "21.0");
        assert_eq!(mc_to_neoforge_prefix("26.1.2"), "26.1.2");
        assert_eq!(mc_to_neoforge_prefix("26.2"), "26.2.0");
    }

    #[test]
    fn neoforge_picks_last_build_of_the_version() {
        let xml = "<versions>\n<version>21.1.1</version>\n<version>21.1.77</version>\n\
                   <version>21.10.3</version>\n<version>21.0.5</version>\n</versions>";
        assert_eq!(
            maven_versions(xml),
            s(&["21.1.1", "21.1.77", "21.10.3", "21.0.5"])
        );
        assert_eq!(neoforge_best(xml, "1.21.1").as_deref(), Some("21.1.77"));
        assert_eq!(neoforge_best(xml, "1.21").as_deref(), Some("21.0.5"));
        assert_eq!(neoforge_best(xml, "1.20.4"), None);
    }
}
