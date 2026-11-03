//! HTTP : client commun, JSON, téléchargement avec progression.
use anyhow::{Context, Result, bail};
use std::io::{Read, Write};
use std::path::Path;
use std::time::Duration;

pub const UA: &str = "ServerCraftAgent/1.1 (local server manager)";

pub fn client() -> reqwest::blocking::Client {
    reqwest::blocking::Client::builder()
        .user_agent(UA)
        .connect_timeout(Duration::from_secs(20))
        .timeout(None)
        .build()
        .expect("client HTTP")
}

pub fn get_json(url: &str) -> Result<serde_json::Value> {
    let r = client()
        .get(url)
        .timeout(Duration::from_secs(30))
        .send()
        .with_context(|| format!("réseau : {url}"))?;
    if !r.status().is_success() {
        bail!("HTTP {} : {url}", r.status().as_u16());
    }
    Ok(r.json()?)
}

pub fn get_text(url: &str) -> Result<String> {
    let r = client()
        .get(url)
        .timeout(Duration::from_secs(30))
        .send()
        .with_context(|| format!("réseau : {url}"))?;
    if !r.status().is_success() {
        bail!("HTTP {} : {url}", r.status().as_u16());
    }
    Ok(r.text()?)
}

/// Télécharge dans `dest` (via un .part, renommé à la fin : jamais de
/// fichier à moitié écrit). `progress(fait, total)` ; total = 0 si inconnu.
pub fn download(url: &str, dest: &Path, progress: Option<&dyn Fn(u64, u64)>) -> Result<()> {
    if let Some(p) = dest.parent() {
        std::fs::create_dir_all(p)?;
    }
    let mut r = client()
        .get(url)
        .send()
        .with_context(|| format!("réseau : {url}"))?;
    if !r.status().is_success() {
        bail!("HTTP {} : {url}", r.status().as_u16());
    }
    let total = r.content_length().unwrap_or(0);
    let part = dest.with_extension("part");
    let mut out = std::fs::File::create(&part)?;
    let mut buf = vec![0u8; 64 * 1024];
    let mut done = 0u64;
    loop {
        let n = r.read(&mut buf)?;
        if n == 0 {
            break;
        }
        out.write_all(&buf[..n])?;
        done += n as u64;
        if let Some(p) = progress {
            p(done, total);
        }
    }
    drop(out);
    std::fs::rename(&part, dest)?;
    Ok(())
}
