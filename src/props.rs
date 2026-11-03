//! Fichiers .properties de Minecraft (server.properties, voicechat…).
use std::collections::BTreeMap;
use std::path::Path;

pub fn load(path: &Path) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    let Ok(text) = std::fs::read_to_string(path) else {
        return out;
    };
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some((k, v)) = line.split_once('=') {
            out.insert(k.trim().to_string(), v.trim().to_string());
        }
    }
    out
}

/// Remplace / ajoute des clés sans toucher aux autres lignes ni aux
/// commentaires.
pub fn update(path: &Path, changes: &[(&str, String)]) -> std::io::Result<()> {
    let text = std::fs::read_to_string(path).unwrap_or_default();
    let mut lines: Vec<String> = text.lines().map(str::to_string).collect();
    for (key, val) in changes {
        let found = lines.iter().position(|l| {
            let t = l.trim_start();
            !t.starts_with('#') && t.split_once('=').is_some_and(|(k, _)| k.trim() == *key)
        });
        let new = format!("{key}={val}");
        match found {
            Some(i) => lines[i] = new,
            None => lines.push(new),
        }
    }
    if let Some(p) = path.parent() {
        std::fs::create_dir_all(p)?;
    }
    std::fs::write(path, lines.join("\n") + "\n")
}

pub fn parse_port(text: &str) -> Option<u16> {
    text.trim().parse::<u16>().ok().filter(|p| *p >= 1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn update_keeps_comments_and_other_keys() {
        let dir = std::env::temp_dir().join(format!("sc-props-{}", std::process::id()));
        let f = dir.join("server.properties");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(&f, "#Minecraft\nmotd=Salut\nserver-port=25565\n").unwrap();
        update(
            &f,
            &[("server-port", "25570".into()), ("pvp", "false".into())],
        )
        .unwrap();
        let text = std::fs::read_to_string(&f).unwrap();
        assert_eq!(
            text,
            "#Minecraft\nmotd=Salut\nserver-port=25570\npvp=false\n"
        );
        assert_eq!(load(&f)["server-port"], "25570");
        std::fs::remove_dir_all(dir).ok();
    }
}
