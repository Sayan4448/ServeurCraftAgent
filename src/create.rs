//! Création d'un serveur. Port du cœur de create_server (app Python) :
//! dossier, jar du loader (+ installeur Forge/NeoForge), eula,
//! server.properties, servercraft.json au même format.
use anyhow::{Context, Result, bail};
use serde_json::{Value, json};
use std::io::BufRead;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use crate::{java, loaders, meta, net, paths};

const INSTALLER_TIMEOUT: Duration = Duration::from_secs(600);

/// server.properties par défaut (DEFAULTS de app/core/properties.py).
const DEFAULT_PROPS: &[(&str, &str)] = &[
    ("server-port", "25565"),
    ("online-mode", "false"), // offline : pas de compte Minecraft requis
    ("motd", "Serveur ServerCraft"),
    ("max-players", "20"),
    ("difficulty", "normal"),
    ("gamemode", "survival"),
    ("view-distance", "10"),
    ("simulation-distance", "10"),
    ("enable-command-block", "false"),
    ("spawn-protection", "0"),
    ("white-list", "false"),
    ("pvp", "true"),
    ("spawn-monsters", "true"),
    ("spawn-animals", "true"),
    ("spawn-npcs", "true"),
    ("allow-nether", "true"),
    ("allow-flight", "true"), // évite les kicks avec certains mods
    ("sync-chunk-writes", "false"),
];

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
    opts: &CreateOptions,
    log: &dyn Fn(&str),
    progress: &dyn Fn(u64, u64),
) -> Result<PathBuf> {
    let name = meta::slug(&opts.name);
    let servers = paths::servers_dir();
    std::fs::create_dir_all(&servers).context("Impossible de créer le dossier des serveurs")?;
    let path = servers.join(&name);
    // create_dir échoue si le dossier existe : un serveur existant n'est jamais touché
    if let Err(e) = std::fs::create_dir(&path) {
        if e.kind() == std::io::ErrorKind::AlreadyExists {
            bail!("Le serveur '{name}' existe déjà.");
        }
        return Err(e).context("Impossible de créer le dossier du serveur");
    }
    let res = fill(&name, &path, opts, log, progress);
    if res.is_err() {
        let _ = std::fs::remove_dir_all(&path);
    }
    res.map(|()| path)
}

fn fill(
    name: &str,
    path: &Path,
    opts: &CreateOptions,
    log: &dyn Fn(&str),
    progress: &dyn Fn(u64, u64),
) -> Result<()> {
    log("— Vérification de Java —");
    let java = java::ensure_java(&opts.mc_version, false, log)?;

    log(&format!(
        "— Résolution {} {} —",
        opts.loader, opts.mc_version
    ));
    let dl = loaders::get_download(&opts.loader, &opts.mc_version, None)?;
    let target = path.join(if dl.installer {
        dl.filename.as_str()
    } else {
        "server.jar"
    });
    log(&format!("Téléchargement : {}", dl.filename));
    net::download(&dl.url, &target, Some(progress))?;
    let mut jar = "server.jar".to_string();
    let mut launch_args = String::new();
    if dl.installer {
        log("Exécution de l'installeur (--installServer), patientez…");
        run_installer(&java, &target, path, log)?;
        launch_args = find_args_file(path);
        if !launch_args.is_empty() {
            log(&format!("Fichier d'arguments détecté : {launch_args}"));
        } else {
            jar = find_forge_jar(path)
                .context("Installeur terminé mais aucun fichier de lancement trouvé.")?;
        }
    }

    std::fs::write(
        path.join("eula.txt"),
        "# Accepté automatiquement par ServerCraft Agent\neula=true\n",
    )?;
    let motd = match opts.motd.trim() {
        "" => format!("{name} - ServerCraft"),
        m => m.to_string(),
    };
    write_server_properties(
        &path.join("server.properties"),
        opts.port,
        opts.online_mode,
        &motd,
    )?;
    log("server.properties généré (mode offline si non coché).");

    for (sub, list) in [
        ("mods", loaders::MOD_LOADERS),
        ("plugins", loaders::PLUGIN_LOADERS),
    ] {
        if list.contains(&opts.loader.as_str()) {
            std::fs::create_dir_all(path.join(sub))?;
        }
    }

    meta::save(
        path,
        &build_meta(name, opts, &jar, &launch_args, &now_utc()),
    )?;
    log(&format!("✔ Serveur '{name}' prêt."));
    Ok(())
}

/// servercraft.json d'un nouveau serveur (mêmes clés que l'app Python ;
/// cross-play, tunnels et voix arriveront plus tard).
fn build_meta(
    name: &str,
    opts: &CreateOptions,
    jar: &str,
    launch_args: &str,
    created: &str,
) -> meta::Meta {
    let accounts = if opts.online_mode { "premium" } else { "both" };
    [
        ("name", json!(name)),
        ("loader", json!(opts.loader)),
        ("mc_version", json!(opts.mc_version)),
        ("ram_mb", json!(opts.ram_mb)),
        ("port", json!(opts.port)),
        ("online_mode", json!(opts.online_mode)),
        ("accounts", json!(accounts)),
        ("crossplay", json!(false)),
        ("tunnels", json!([])),
        ("playit_auto", json!(opts.playit_auto)),
        ("voice", json!("none")),
        ("jar", json!(jar)),
        ("launch_args", json!(launch_args)),
        ("created", json!(created)),
    ]
    .into_iter()
    .map(|(k, v): (&str, Value)| (k.to_string(), v))
    .collect()
}

/// Fichier complet, clés dans l'ordre de l'app Python (write_server_properties).
fn write_server_properties(
    file: &Path,
    port: u16,
    online: bool,
    motd: &str,
) -> std::io::Result<()> {
    let lines: Vec<String> = DEFAULT_PROPS
        .iter()
        .map(|&(k, v)| match k {
            "server-port" => format!("{k}={port}"),
            "online-mode" => format!("{k}={online}"),
            "motd" => format!("{k}={motd}"),
            _ => format!("{k}={v}"),
        })
        .collect();
    std::fs::write(file, lines.join("\n") + "\n")
}

/// "%Y-%m-%d %H:%M".
/// shortcut: heure UTC (std n'a pas de fuseau horaire) ; passer à chrono si
/// la date de création doit s'afficher à l'heure locale.
fn now_utc() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs());
    format_time(secs)
}

fn format_time(secs: u64) -> String {
    let (days, rem) = ((secs / 86_400) as i64, secs % 86_400);
    // jours depuis 1970 -> date civile (algorithme de H. Hinnant)
    let z = days + 719_468;
    let (era, doe) = (z / 146_097, z % 146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!(
        "{y:04}-{m:02}-{d:02} {:02}:{:02}",
        rem / 3600,
        rem % 3600 / 60
    )
}

/// `java -jar installeur --installServer` dans le dossier du serveur, sortie
/// (stdout + stderr) envoyée à `log`, arrêté au bout de 10 min.
fn run_installer(java: &Path, installer: &Path, cwd: &Path, log: &dyn Fn(&str)) -> Result<()> {
    let (reader, writer) = std::io::pipe()?;
    let mut child = java::hide_window(
        Command::new(java)
            .arg("-jar")
            .arg(installer)
            .arg("--installServer"),
    )
    .current_dir(cwd)
    .stdin(Stdio::null())
    .stdout(writer.try_clone()?)
    .stderr(writer)
    .spawn()
    .context("Impossible de lancer l'installeur (Java)")?;
    // log n'est pas Send : un thread lit le tube, celui-ci affiche
    let (tx, rx) = mpsc::channel::<String>();
    std::thread::spawn(move || {
        let mut r = std::io::BufReader::new(reader);
        let mut buf = Vec::new();
        while matches!(r.read_until(b'\n', &mut buf), Ok(n) if n > 0) {
            if tx
                .send(String::from_utf8_lossy(&buf).trim().to_string())
                .is_err()
            {
                break;
            }
            buf.clear();
        }
    });
    let deadline = Instant::now() + INSTALLER_TIMEOUT;
    while let Ok(line) = rx.recv_timeout(deadline.saturating_duration_since(Instant::now())) {
        if !line.is_empty() {
            log(&format!("  {line}"));
        }
    }
    let status = java::wait_timeout(
        &mut child,
        deadline.saturating_duration_since(Instant::now()),
    )
    .context("L'installeur ne répond plus après 10 minutes : il a été arrêté.")?;
    if !status.success() {
        let code = status.code().map_or("?".to_string(), |c| c.to_string());
        bail!("L'installeur a échoué (code {code}).");
    }
    Ok(())
}

/// Forge/NeoForge modernes : win_args.txt / unix_args.txt dans libraries/,
/// chemin relatif au dossier du serveur ("" si absent).
fn find_args_file(dir: &Path) -> String {
    let argname = if cfg!(windows) {
        "win_args.txt"
    } else {
        "unix_args.txt"
    };
    for group in [
        ["net", "minecraftforge", "forge"],
        ["net", "neoforged", "neoforge"],
        ["net", "neoforged", "forge"],
    ] {
        let base: PathBuf = std::iter::once("libraries").chain(group).collect();
        let Ok(rd) = std::fs::read_dir(dir.join(&base)) else {
            continue;
        };
        let mut subs: Vec<_> = rd.flatten().map(|e| e.file_name()).collect();
        subs.sort();
        if let Some(sub) = subs
            .into_iter()
            .find(|s| dir.join(&base).join(s).join(argname).exists())
        {
            return base.join(sub).join(argname).to_string_lossy().into_owned();
        }
    }
    String::new()
}

/// Forge ancien (< 1.17) : forge-x.y.z-server.jar (ou -universal) à la racine.
fn find_forge_jar(dir: &Path) -> Option<String> {
    let mut jars: Vec<String> = std::fs::read_dir(dir)
        .ok()?
        .flatten()
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| n.starts_with("forge-") && n.ends_with(".jar") && !n.contains("installer"))
        .collect();
    jars.sort();
    jars.into_iter().next()
}

/// Premier port ≥ 25565 qu'aucun serveur de la liste n'utilise.
pub fn free_port() -> u16 {
    let used: std::collections::HashSet<i64> = meta::list_servers()
        .iter()
        .map(|s| meta::int_of(&s.meta, "port", 25565))
        .collect();
    let mut port: u16 = 25565;
    while used.contains(&i64::from(port)) && port < 65535 {
        port += 1;
    }
    port
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    /// SERVERCRAFT_HOME est global au process : tout test qui le change
    /// doit tenir ce verrou.
    static HOME_LOCK: Mutex<()> = Mutex::new(());

    fn opts(port: u16) -> CreateOptions {
        CreateOptions {
            name: "Mon Serveur".into(),
            loader: "paper".into(),
            mc_version: "1.21.4".into(),
            ram_mb: 4096,
            port,
            motd: String::new(),
            online_mode: false,
            playit_auto: true,
        }
    }

    fn temp_dir(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("sc-create-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn meta_has_the_python_keys() {
        let m = build_meta(
            "mon-serveur",
            &opts(25570),
            "server.jar",
            "",
            "2026-11-03 14:05",
        );
        assert_eq!(
            Value::Object(m),
            json!({
                "name": "mon-serveur", "loader": "paper", "mc_version": "1.21.4",
                "ram_mb": 4096, "port": 25570, "online_mode": false,
                "accounts": "both", "crossplay": false, "tunnels": [],
                "playit_auto": true, "voice": "none", "jar": "server.jar",
                "launch_args": "", "created": "2026-11-03 14:05",
            })
        );
        let premium = CreateOptions {
            online_mode: true,
            ..opts(25565)
        };
        assert_eq!(
            build_meta("x", &premium, "j", "", "")["accounts"],
            "premium"
        );
    }

    #[test]
    fn server_properties_like_python() {
        let dir = temp_dir("props");
        let f = dir.join("server.properties");
        write_server_properties(&f, 25570, true, "Salut").unwrap();
        let text = std::fs::read_to_string(&f).unwrap();
        assert!(
            text.starts_with("server-port=25570\nonline-mode=true\nmotd=Salut\nmax-players=20\n")
        );
        assert!(text.ends_with("allow-flight=true\nsync-chunk-writes=false\n"));
        assert_eq!(text.lines().count(), DEFAULT_PROPS.len());
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn created_date_format() {
        assert_eq!(format_time(0), "1970-01-01 00:00");
        assert_eq!(format_time(951_782_400), "2000-02-29 00:00");
        assert_eq!(format_time(1_700_000_000), "2023-11-14 22:13");
        assert_eq!(now_utc().len(), "2026-11-03 14:05".len());
    }

    #[test]
    fn forge_launch_files_are_found() {
        let dir = temp_dir("forge");
        assert_eq!(find_args_file(&dir), "");
        assert_eq!(find_forge_jar(&dir), None);
        for f in [
            "forge-1.16.5-36.2.39-installer.jar",
            "forge-1.16.5-36.2.39.jar",
        ] {
            std::fs::write(dir.join(f), "").unwrap();
        }
        assert_eq!(
            find_forge_jar(&dir).as_deref(),
            Some("forge-1.16.5-36.2.39.jar")
        );
        let argname = if cfg!(windows) {
            "win_args.txt"
        } else {
            "unix_args.txt"
        };
        let rel: PathBuf = [
            "libraries",
            "net",
            "neoforged",
            "neoforge",
            "21.1.77",
            argname,
        ]
        .iter()
        .collect();
        std::fs::create_dir_all(dir.join(&rel).parent().unwrap()).unwrap();
        std::fs::write(dir.join(&rel), "").unwrap();
        assert_eq!(find_args_file(&dir), rel.to_string_lossy());
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn free_port_and_taken_name_in_a_temp_home() {
        let _guard = HOME_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let home = temp_dir("home");
        // SAFETY : variable protégée par HOME_LOCK
        unsafe { std::env::set_var("SERVERCRAFT_HOME", &home) };
        assert_eq!(free_port(), 25565);
        for (name, port) in [("a", 25565), ("b", 25566), ("c", 25568)] {
            let d = paths::servers_dir().join(name);
            std::fs::create_dir_all(&d).unwrap();
            meta::save(&d, &build_meta(name, &opts(port), "server.jar", "", "")).unwrap();
        }
        assert_eq!(free_port(), 25567);
        // nom déjà pris : refusé avant tout téléchargement, l'existant reste
        let taken = CreateOptions {
            name: "A".into(),
            ..opts(25570)
        };
        let err = create_server(&taken, &|_| {}, &|_, _| {}).unwrap_err();
        assert!(err.to_string().contains("existe déjà"), "{err}");
        assert!(
            paths::servers_dir()
                .join("a")
                .join(meta::META_FILE)
                .exists()
        );
        unsafe { std::env::remove_var("SERVERCRAFT_HOME") };
        std::fs::remove_dir_all(home).ok();
    }
}
