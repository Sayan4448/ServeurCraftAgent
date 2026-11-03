//! Interface (egui). Les tâches longues (téléchargements, Java, Playit)
//! tournent dans des threads qui remplissent des `Shared` ; l'interface les
//! lit à chaque image et se redessine toute seule tant que ça bouge.
use eframe::egui::{self, Color32, RichText};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use crate::create::{self, CreateOptions};
use crate::meta::{self, ServerInfo};
use crate::process::{ServerProcess, Status};
use crate::{backups, loaders, playit};

pub const VERSION_LABEL: &str = concat!("v", env!("CARGO_PKG_VERSION"), " Rust · préversion");

const BG: Color32 = Color32::from_rgb(0x0b, 0x0e, 0x13);
const PANEL: Color32 = Color32::from_rgb(0x13, 0x18, 0x20);
const PANEL_2: Color32 = Color32::from_rgb(0x1a, 0x21, 0x2c);
const CONSOLE_BG: Color32 = Color32::from_rgb(0x08, 0x0a, 0x0e);
const ACCENT: Color32 = Color32::from_rgb(0x3b, 0x82, 0xf6);
const GREEN: Color32 = Color32::from_rgb(0x22, 0xc5, 0x5e);
const RED: Color32 = Color32::from_rgb(0xef, 0x44, 0x44);
const ORANGE: Color32 = Color32::from_rgb(0xf5, 0x9e, 0x0b);
const MUTED: Color32 = Color32::from_rgb(0x8b, 0x94, 0xa7);
const TEXT: Color32 = Color32::from_rgb(0xe6, 0xe9, 0xef);
const MAX_LINES: usize = 4000;

type Shared<T> = Arc<Mutex<Option<T>>>;

pub fn run() -> eframe::Result {
    let opts = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("ServerCraft Agent (Rust)")
            .with_inner_size([1100.0, 700.0])
            .with_min_inner_size([820.0, 520.0]),
        ..Default::default()
    };
    eframe::run_native(
        "ServerCraft Agent",
        opts,
        Box::new(|cc| {
            style(&cc.egui_ctx);
            Ok(Box::new(App::default()))
        }),
    )
}

fn style(ctx: &egui::Context) {
    let mut v = egui::Visuals::dark();
    v.panel_fill = BG;
    v.window_fill = PANEL;
    v.extreme_bg_color = CONSOLE_BG;
    v.faint_bg_color = PANEL_2;
    v.selection.bg_fill = ACCENT;
    v.hyperlink_color = ACCENT;
    v.override_text_color = Some(TEXT);
    ctx.set_visuals(v);
    ctx.all_styles_mut(|s| {
        s.spacing.item_spacing = egui::vec2(8.0, 6.0);
        s.spacing.button_padding = egui::vec2(10.0, 5.0);
        for (ts, size) in [
            (egui::TextStyle::Body, 14.0),
            (egui::TextStyle::Button, 14.0),
            (egui::TextStyle::Monospace, 13.0),
            (egui::TextStyle::Heading, 20.0),
        ] {
            if let Some(f) = s.text_styles.get_mut(&ts) {
                f.size = size;
            }
        }
    });
}

/// Console d'un serveur, copiée petit à petit depuis son ServerProcess.
#[derive(Default)]
struct Console {
    lines: Vec<String>,
    seq: u64,
}

struct CreateDialog {
    name: String,
    loader: String,
    versions: Shared<Result<Vec<String>, String>>,
    versions_for: String,
    version: String,
    ram_gb: f32,
    port: String,
    motd: String,
    online: bool,
    playit: bool,
    error: String,
    job: Option<CreateJob>,
}

struct CreateJob {
    log: Arc<Mutex<Vec<String>>>,
    progress: Arc<Mutex<(u64, u64)>>,
    result: Shared<Result<PathBuf, String>>,
}

#[derive(Default)]
struct PlayitDialog {
    status: Arc<Mutex<String>>,
    url: Arc<Mutex<String>>,
    cancel: Arc<AtomicBool>,
    busy: Arc<AtomicBool>,
}

/// Fenêtre Sauvegardes d'un serveur.
struct BackupsDialog {
    server: String,
    dir: PathBuf,
    list: Vec<backups::Backup>,
    confirm: Option<(PathBuf, bool)>, // (fichier, true = restaurer)
    on_stop: bool,
    interval_min: i64,
    keep: i64,
    status: Arc<Mutex<String>>,
    busy: Arc<AtomicBool>,
    done: Arc<AtomicBool>,
}

#[derive(Default)]
struct App {
    servers: Vec<ServerInfo>,
    listed_at: Option<Instant>,
    selected: Option<String>,
    procs: HashMap<String, ServerProcess>,
    consoles: HashMap<String, Console>,
    input: String,
    create: Option<CreateDialog>,
    playit: Option<PlayitDialog>,
    playit_linked: Option<bool>,
    backups: Option<BackupsDialog>,
    closing: bool,
}

impl App {
    fn proc(&mut self, info: &ServerInfo) -> ServerProcess {
        self.procs
            .entry(info.name.clone())
            .or_insert_with(|| ServerProcess::new(&info.name, info.dir.clone()))
            .clone()
    }

    fn refresh(&mut self, force: bool) {
        if force
            || self
                .listed_at
                .is_none_or(|t| t.elapsed() > Duration::from_secs(2))
        {
            self.servers = meta::list_servers();
            self.listed_at = Some(Instant::now());
            self.playit_linked = Some(playit::linked());
            if self.selected.is_none() {
                self.selected = self.servers.first().map(|s| s.name.clone());
            }
        }
    }

    fn any_running(&self) -> bool {
        self.procs.values().any(|p| p.is_running())
    }
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let ctx = ui.ctx().clone();
        self.refresh(false);
        self.handle_close(&ctx);

        egui::Panel::top("top").show(ui, |ui| self.top_bar(ui));
        egui::Panel::left("servers")
            .resizable(true)
            .default_size(250.0)
            .show(ui, |ui| self.server_list(ui));
        egui::CentralPanel::default().show(ui, |ui| self.server_view(ui));

        self.create_window(&ctx);
        self.playit_window(&ctx);
        self.backups_window(&ctx);
        // threads (console, téléchargements) : on se redessine régulièrement
        ctx.request_repaint_after(Duration::from_millis(250));
    }
}

impl App {
    /// Fermeture : on arrête proprement les serveurs lancés avant de quitter.
    fn handle_close(&mut self, ctx: &egui::Context) {
        let asked = ctx.input(|i| i.viewport().close_requested());
        if asked && !self.closing && self.any_running() {
            ctx.send_viewport_cmd(egui::ViewportCommand::CancelClose);
            self.closing = true;
            for p in self.procs.values() {
                p.stop();
            }
        } else if self.closing && !self.any_running() {
            self.closing = false;
            playit::stop_agent();
            ctx.send_viewport_cmd(egui::ViewportCommand::Close);
        } else if asked && !self.closing {
            playit::stop_agent();
        }
    }

    fn top_bar(&mut self, ui: &mut egui::Ui) {
        ui.add_space(6.0);
        ui.horizontal(|ui| {
            ui.label(RichText::new("ServerCraft Agent").heading().strong());
            ui.label(RichText::new(VERSION_LABEL).small().color(ORANGE));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let linked = self.playit_linked.unwrap_or(false);
                let txt = if linked {
                    "🌐 Playit : lié"
                } else {
                    "🌐 Lier Playit"
                };
                if ui.button(txt).clicked() {
                    self.playit = Some(PlayitDialog::default());
                }
                if ui.button("＋ Nouveau serveur").clicked() {
                    self.create = Some(CreateDialog::new());
                }
            });
        });
        if self.closing {
            ui.colored_label(ORANGE, "Arrêt des serveurs avant de quitter…");
        }
        ui.add_space(4.0);
    }

    fn server_list(&mut self, ui: &mut egui::Ui) {
        ui.add_space(6.0);
        ui.label(RichText::new("Mes serveurs").strong());
        ui.separator();
        if self.servers.is_empty() {
            ui.label(
                RichText::new("Aucun serveur. Créez-en un avec « ＋ Nouveau serveur ».")
                    .color(MUTED),
            );
        }
        let servers = self.servers.clone();
        egui::ScrollArea::vertical().show(ui, |ui| {
            ui.with_layout(egui::Layout::top_down_justified(egui::Align::LEFT), |ui| {
                self.server_rows(ui, &servers)
            });
        });
    }

    fn server_rows(&mut self, ui: &mut egui::Ui, servers: &[ServerInfo]) {
        for s in servers {
            let st = self.proc(s).status();
            let (dot, col) = status_dot(&st);
            let sel = self.selected.as_deref() == Some(&s.name);
            let text = format!(
                "{dot} {}\n   {} {}",
                s.name,
                meta::str_of(&s.meta, "loader"),
                meta::str_of(&s.meta, "mc_version")
            );
            let r = ui.add(
                egui::Button::selectable(
                    sel,
                    RichText::new(text).color(if sel { TEXT } else { col }),
                )
                .min_size(egui::vec2(0.0, 40.0)),
            );
            if r.clicked() {
                self.selected = Some(s.name.clone());
            }
        }
    }

    fn server_view(&mut self, ui: &mut egui::Ui) {
        let Some(info) = self
            .selected
            .clone()
            .and_then(|n| self.servers.iter().find(|s| s.name == n).cloned())
        else {
            ui.centered_and_justified(|ui| {
                ui.label(RichText::new("Sélectionnez ou créez un serveur").color(MUTED));
            });
            return;
        };
        let proc = self.proc(&info);
        let st = proc.status();
        let m = &info.meta;

        // ---------------------------------------------------------- en-tête
        ui.horizontal(|ui| {
            ui.heading(&info.name);
            let (dot, col) = status_dot(&st);
            ui.colored_label(col, format!("{dot} {}", status_text(&st)));
        });
        ui.label(
            RichText::new(format!(
                "{} {} · port {} · {} Mo de RAM",
                meta::str_of(m, "loader"),
                meta::str_of(m, "mc_version"),
                meta::int_of(m, "port", 25565),
                meta::int_of(m, "ram_mb", 4096)
            ))
            .color(MUTED),
        );
        ui.add_space(4.0);
        ui.horizontal(|ui| {
            let running = st.running || st.starting;
            if ui
                .add_enabled(
                    !running,
                    egui::Button::new("▶ Lancer").fill(GREEN.gamma_multiply(0.6)),
                )
                .clicked()
            {
                proc.start();
            }
            if ui
                .add_enabled(
                    st.running && !st.stopping,
                    egui::Button::new("■ Arrêter").fill(RED.gamma_multiply(0.5)),
                )
                .clicked()
            {
                proc.stop();
            }
            let saving = backups::busy(&info.name);
            if ui
                .add_enabled(!saving, egui::Button::new("💾 Sauvegarder"))
                .on_hover_text("Copie du monde maintenant (le serveur peut rester lancé)")
                .clicked()
            {
                let p = proc.clone();
                std::thread::spawn(move || {
                    p.backup("manual");
                });
            }
            if ui.button("🗂 Sauvegardes").clicked() {
                self.backups = Some(BackupsDialog::new(&info));
            }
            if ui.button("📁 Dossier").clicked() {
                if let Err(e) = open::that(&info.dir) {
                    proc.log(&format!("✖ Ouverture du dossier : {e}"));
                }
            }
            let linked = self.playit_linked.unwrap_or(false);
            let tip = if linked {
                "Crée ou retrouve les tunnels Java, Bedrock et Voice Chat"
            } else {
                "Liez d'abord votre compte Playit (en haut à droite)"
            };
            if ui
                .add_enabled(linked, egui::Button::new("🌐 Tunnels Playit"))
                .on_hover_text(tip)
                .on_disabled_hover_text(tip)
                .clicked()
            {
                proc.tunnels();
            }
        });

        // ------------------------------------------------- adresses, joueurs
        let tunnels = m
            .get("tunnels")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        if !tunnels.is_empty() {
            ui.horizontal_wrapped(|ui| {
                for tn in &tunnels {
                    let addr = tn.get("address").and_then(|v| v.as_str()).unwrap_or("");
                    if addr.is_empty() {
                        continue;
                    }
                    let name = tn.get("name").and_then(|v| v.as_str()).unwrap_or("Tunnel");
                    ui.label(RichText::new(format!("{name} :")).color(MUTED));
                    if ui
                        .button(RichText::new(addr).monospace())
                        .on_hover_text("Copier l'adresse")
                        .clicked()
                    {
                        ui.ctx().copy_text(addr.to_string());
                    }
                }
            });
        }
        if st.running {
            let players = if st.players.is_empty() {
                "aucun".to_string()
            } else {
                st.players.join(", ")
            };
            let up = st.uptime.map(fmt_uptime).unwrap_or_default();
            ui.label(
                RichText::new(format!(
                    "Joueurs ({}) : {players}   ·   en ligne depuis {up}",
                    st.players.len()
                ))
                .color(MUTED),
            );
        }
        ui.add_space(4.0);

        // ------------------------------------------------------------ console
        let console = self.consoles.entry(info.name.clone()).or_default();
        let (new, seq) = proc.lines_since(console.seq);
        console.seq = seq;
        console.lines.extend(new);
        if console.lines.len() > MAX_LINES {
            let cut = console.lines.len() - MAX_LINES;
            console.lines.drain(..cut);
        }
        let input_h = 36.0;
        let console_h = (ui.available_height() - input_h - 24.0).max(80.0);
        egui::Frame::new()
            .fill(CONSOLE_BG)
            .corner_radius(8.0)
            .inner_margin(8.0)
            .show(ui, |ui| {
                ui.set_min_height(console_h);
                let row_h = ui.text_style_height(&egui::TextStyle::Monospace);
                egui::ScrollArea::vertical()
                    .auto_shrink(false)
                    .stick_to_bottom(true)
                    .max_height(console_h)
                    .show_rows(ui, row_h, console.lines.len(), |ui, range| {
                        for line in &console.lines[range] {
                            ui.label(RichText::new(line).monospace().color(line_color(line)));
                        }
                    });
            });
        ui.add_space(4.0);
        ui.horizontal(|ui| {
            let edit = ui.add_enabled(
                st.running,
                egui::TextEdit::singleline(&mut self.input)
                    .hint_text("Commande console (ex : say Bonjour, op pseudo)…")
                    .desired_width(ui.available_width() - 100.0),
            );
            let enter = edit.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter));
            if (ui
                .add_enabled(st.running, egui::Button::new("Envoyer"))
                .clicked()
                || enter)
                && !self.input.trim().is_empty()
            {
                let cmd = std::mem::take(&mut self.input);
                proc.log(&format!("> {}", cmd.trim()));
                if !proc.send(&cmd) {
                    proc.log("✖ Le serveur n'est pas lancé.");
                }
                edit.request_focus();
            }
        });
    }

    fn create_window(&mut self, ctx: &egui::Context) {
        let Some(d) = self.create.as_mut() else {
            return;
        };
        let mut open = true;
        let mut done: Option<String> = None;
        egui::Window::new("Nouveau serveur")
            .open(&mut open)
            .collapsible(false)
            .resizable(true)
            .default_width(440.0)
            .show(ctx, |ui| match &d.job {
                Some(job) => d.show_job(ui, job, &mut done),
                None => d.form(ui),
            });
        if let Some(name) = done {
            self.refresh(true);
            self.selected = Some(name);
            self.create = None;
        } else if !open
            && self
                .create
                .as_ref()
                .is_some_and(|d| d.job.is_none() || d.finished())
        {
            // une création en cours continue : la fenêtre reste ouverte
            self.refresh(true);
            self.create = None;
        }
    }

    fn playit_window(&mut self, ctx: &egui::Context) {
        let Some(d) = self.playit.as_mut() else {
            return;
        };
        let mut open = true;
        let mut relist = false;
        egui::Window::new("Playit.gg")
            .open(&mut open)
            .collapsible(false)
            .resizable(false)
            .default_width(380.0)
            .show(ctx, |ui| {
                ui.label("Une adresse gratuite pour vos joueurs, sans ouvrir de port sur la box ni donner votre IP.");
                ui.add_space(6.0);
                let busy = d.busy.load(Ordering::Relaxed);
                if busy {
                    ui.horizontal(|ui| {
                        ui.spinner();
                        ui.label(d.status.lock().unwrap().clone());
                    });
                    let url = d.url.lock().unwrap().clone();
                    ui.horizontal(|ui| {
                        if ui.button("↗ Rouvrir la page").clicked() {
                            let _ = open::that(&url);
                        }
                        if ui.button("📋 Copier le lien").clicked() {
                            ui.ctx().copy_text(url.clone());
                        }
                    });
                } else if playit::linked() {
                    ui.colored_label(GREEN, "✔ Compte Playit lié.");
                    ui.label(
                        RichText::new("Les tunnels se créent avec « 🌐 Tunnels Playit » sur chaque serveur.").color(MUTED),
                    );
                    if ui.button("Délier le compte").clicked() {
                        playit::unlink();
                        relist = true;
                    }
                } else {
                    let msg = d.status.lock().unwrap().clone();
                    if !msg.is_empty() {
                        ui.colored_label(RED, msg);
                    }
                    if ui.button("Lier mon compte Playit (navigateur)").clicked() {
                        d.start_link();
                    }
                }
            });
        if !open {
            if let Some(d) = &self.playit {
                d.cancel.store(true, Ordering::Relaxed);
            }
            self.playit = None;
            relist = true;
        }
        if relist {
            self.refresh(true);
        }
    }
}

impl App {
    fn backups_window(&mut self, ctx: &egui::Context) {
        let Some(d) = self.backups.as_mut() else {
            return;
        };
        let running = self.procs.get(&d.server).is_some_and(|p| p.is_running());
        let proc = self.procs.get(&d.server).cloned();
        let mut open = true;
        egui::Window::new(format!("Sauvegardes — {}", d.server))
            .open(&mut open)
            .collapsible(false)
            .default_width(520.0)
            .show(ctx, |ui| d.show(ui, running, proc));
        if !open {
            self.backups = None;
        }
    }
}

impl BackupsDialog {
    fn new(info: &ServerInfo) -> Self {
        let m = meta::load(&info.dir).unwrap_or_else(|_| info.meta.clone());
        Self {
            server: info.name.clone(),
            dir: info.dir.clone(),
            list: backups::list(&info.name),
            confirm: None,
            on_stop: m
                .get("backup_on_stop")
                .and_then(|v| v.as_bool())
                .unwrap_or(true),
            interval_min: meta::int_of(&m, "backup_interval_min", 0),
            keep: meta::int_of(&m, "backup_keep", backups::DEFAULT_KEEP),
            status: Default::default(),
            busy: Default::default(),
            done: Default::default(),
        }
    }

    fn show(&mut self, ui: &mut egui::Ui, running: bool, proc: Option<ServerProcess>) {
        let busy = self.busy.load(Ordering::Relaxed) || backups::busy(&self.server);
        // ------------------------------------------------------ réglages
        ui.checkbox(&mut self.on_stop, "Sauvegarder avant chaque arrêt");
        ui.horizontal(|ui| {
            ui.label("Sauvegarde automatique toutes les");
            ui.add(
                egui::DragValue::new(&mut self.interval_min)
                    .range(0..=1440)
                    .suffix(" min"),
            );
            ui.label(RichText::new("(0 = jamais)").color(MUTED));
        });
        ui.horizontal(|ui| {
            ui.label("Garder les");
            ui.add(egui::DragValue::new(&mut self.keep).range(1..=200));
            ui.label("dernières sauvegardes automatiques");
        });
        ui.horizontal(|ui| {
            if ui.button("Enregistrer les réglages").clicked() {
                *self.status.lock().unwrap() = match self.save_settings() {
                    Ok(()) => "✔ Réglages enregistrés.".into(),
                    Err(e) => format!("✖ {e:#}"),
                };
            }
            if ui.button("📁 Dossier des sauvegardes").clicked() {
                let d = backups::backup_dir(&self.server);
                let _ = std::fs::create_dir_all(&d);
                let _ = open::that(d);
            }
        });
        ui.label(
            RichText::new("Les sauvegardes manuelles ne sont jamais supprimées automatiquement.")
                .color(MUTED)
                .small(),
        );
        ui.separator();

        // ------------------------------------------------------------ liste
        if !busy && ui.small_button("⟳ Actualiser").clicked() {
            self.list = backups::list(&self.server);
        }
        if self.list.is_empty() {
            ui.label(RichText::new("Aucune sauvegarde pour l'instant.").color(MUTED));
        }
        let mut action: Option<(PathBuf, bool)> = None;
        egui::ScrollArea::vertical()
            .max_height(300.0)
            .show(ui, |ui| {
                egui::Grid::new("backups")
                    .num_columns(4)
                    .striped(true)
                    .spacing([14.0, 6.0])
                    .show(ui, |ui| {
                        for b in &self.list {
                            ui.label(&b.date);
                            ui.label(RichText::new(backups::reason_label(&b.reason)).color(MUTED));
                            ui.label(backups::fmt_size(b.size));
                            ui.horizontal(|ui| {
                                let restore_tip = if running {
                                    "Arrêtez d'abord le serveur"
                                } else {
                                    "Remplace le monde actuel (sauvegardé avant)"
                                };
                                if ui
                                    .add_enabled(!running && !busy, egui::Button::new("Restaurer"))
                                    .on_hover_text(restore_tip)
                                    .on_disabled_hover_text(restore_tip)
                                    .clicked()
                                {
                                    action = Some((b.path.clone(), true));
                                }
                                if ui
                                    .add_enabled(!busy, egui::Button::new("🗑"))
                                    .on_hover_text("Supprimer")
                                    .clicked()
                                {
                                    action = Some((b.path.clone(), false));
                                }
                            });
                            ui.end_row();
                        }
                    });
            });
        if action.is_some() {
            self.confirm = action;
        }

        // --------------------------------------------------- confirmation
        if let Some((path, restore)) = self.confirm.clone() {
            ui.separator();
            let file = path
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .to_string();
            ui.colored_label(
                ORANGE,
                if restore {
                    format!("Restaurer {file} ? Le monde actuel sera remplacé (une sauvegarde en est faite avant).")
                } else {
                    format!("Supprimer définitivement {file} ?")
                },
            );
            ui.horizontal(|ui| {
                if ui
                    .add(egui::Button::new("Confirmer").fill(RED.gamma_multiply(0.5)))
                    .clicked()
                {
                    self.confirm = None;
                    if restore {
                        self.restore(path.clone(), proc.clone());
                    } else {
                        *self.status.lock().unwrap() = match std::fs::remove_file(&path) {
                            Ok(()) => "✔ Sauvegarde supprimée.".into(),
                            Err(e) => format!("✖ {e}"),
                        };
                        self.list = backups::list(&self.server);
                    }
                }
                if ui.button("Annuler").clicked() {
                    self.confirm = None;
                }
            });
        }
        let msg = self.status.lock().unwrap().clone();
        if busy {
            ui.horizontal(|ui| {
                ui.spinner();
                ui.label(if msg.is_empty() {
                    "Sauvegarde en cours…".to_string()
                } else {
                    msg
                });
            });
        } else if !msg.is_empty() {
            ui.label(msg);
        }
        // restauration terminée : la sauvegarde « avant restauration » apparaît
        if self.done.swap(false, Ordering::Relaxed) {
            self.list = backups::list(&self.server);
        }
    }

    fn restore(&mut self, path: PathBuf, proc: Option<ServerProcess>) {
        self.busy.store(true, Ordering::Relaxed);
        *self.status.lock().unwrap() = "Restauration en cours…".into();
        let (status, busy, done) = (self.status.clone(), self.busy.clone(), self.done.clone());
        let (name, dir, keep) = (self.server.clone(), self.dir.clone(), self.keep);
        std::thread::spawn(move || {
            let log = |s: &str| {
                if let Some(p) = &proc {
                    p.log(s);
                }
            };
            *status.lock().unwrap() = match backups::restore(&name, &dir, &path, keep, &log) {
                Ok(()) => "✔ Monde restauré.".into(),
                Err(e) => format!("✖ Restauration impossible : {e:#}"),
            };
            busy.store(false, Ordering::Relaxed);
            done.store(true, Ordering::Relaxed);
        });
    }

    fn save_settings(&self) -> anyhow::Result<()> {
        let mut m = meta::load(&self.dir)?;
        m.insert("backup_on_stop".into(), self.on_stop.into());
        m.insert("backup_interval_min".into(), self.interval_min.into());
        m.insert("backup_keep".into(), self.keep.into());
        meta::save(&self.dir, &m)
    }
}

impl CreateDialog {
    fn new() -> Self {
        let mut d = Self {
            name: String::new(),
            loader: "paper".into(),
            versions: Default::default(),
            versions_for: String::new(),
            version: String::new(),
            ram_gb: 4.0,
            port: create::free_port().to_string(),
            motd: "Serveur ServerCraft".into(),
            online: false,
            playit: false,
            error: String::new(),
            job: None,
        };
        d.fetch_versions();
        d
    }

    fn fetch_versions(&mut self) {
        self.versions_for = self.loader.clone();
        self.version.clear();
        let slot: Shared<Result<Vec<String>, String>> = Default::default();
        self.versions = slot.clone();
        let loader = self.loader.clone();
        std::thread::spawn(move || {
            let r = loaders::versions(&loader).map_err(|e| format!("{e:#}"));
            *slot.lock().unwrap() = Some(r);
        });
    }

    fn form(&mut self, ui: &mut egui::Ui) {
        egui::Grid::new("create")
            .num_columns(2)
            .spacing([12.0, 8.0])
            .show(ui, |ui| {
                ui.label("Nom");
                ui.add(egui::TextEdit::singleline(&mut self.name).hint_text("Survie entre potes"));
                ui.end_row();

                ui.label("Type");
                let label = loaders::LOADERS
                    .iter()
                    .find(|(k, _)| *k == self.loader)
                    .map(|(_, l)| *l)
                    .unwrap_or("?");
                egui::ComboBox::from_id_salt("loader")
                    .selected_text(label)
                    .show_ui(ui, |ui| {
                        for (k, l) in loaders::LOADERS {
                            ui.selectable_value(&mut self.loader, k.to_string(), *l);
                        }
                    });
                ui.end_row();

                ui.label("Version");
                let versions = self.versions.lock().unwrap().clone();
                match versions {
                    None => {
                        ui.horizontal(|ui| {
                            ui.spinner();
                            ui.label("Chargement des versions…");
                        });
                    }
                    Some(Err(e)) => {
                        ui.colored_label(RED, format!("✖ {e}"));
                    }
                    Some(Ok(list)) => {
                        if self.version.is_empty() {
                            self.version = list.first().cloned().unwrap_or_default();
                        }
                        egui::ComboBox::from_id_salt("version")
                            .selected_text(self.version.clone())
                            .height(300.0)
                            .show_ui(ui, |ui| {
                                for v in &list {
                                    ui.selectable_value(&mut self.version, v.clone(), v);
                                }
                            });
                    }
                }
                ui.end_row();

                ui.label("RAM");
                ui.add(
                    egui::Slider::new(&mut self.ram_gb, 1.0..=16.0)
                        .step_by(0.5)
                        .suffix(" Go"),
                );
                ui.end_row();

                ui.label("Port");
                ui.add(egui::TextEdit::singleline(&mut self.port).desired_width(80.0));
                ui.end_row();

                ui.label("Message (MOTD)");
                ui.text_edit_singleline(&mut self.motd);
                ui.end_row();
            });
        if self.loader != self.versions_for {
            self.fetch_versions();
        }
        ui.checkbox(
            &mut self.online,
            "Comptes Minecraft officiels uniquement (premium)",
        );
        ui.checkbox(&mut self.playit, "Adresse gratuite Playit.gg au lancement");
        if !self.error.is_empty() {
            ui.colored_label(RED, &self.error);
        }
        ui.add_space(6.0);
        if ui
            .add(egui::Button::new("Créer le serveur").fill(ACCENT))
            .clicked()
        {
            self.submit();
        }
    }

    fn submit(&mut self) {
        let name = self.name.trim().to_string();
        let Some(port) = crate::props::parse_port(&self.port) else {
            self.error = "Port invalide (1 à 65535).".into();
            return;
        };
        if name.is_empty() {
            self.error = "Donnez un nom au serveur.".into();
            return;
        }
        if self.version.is_empty() {
            self.error = "Choisissez une version.".into();
            return;
        }
        let opts = CreateOptions {
            name,
            loader: self.loader.clone(),
            mc_version: self.version.clone(),
            ram_mb: (self.ram_gb * 1024.0) as u32,
            port,
            motd: self.motd.clone(),
            online_mode: self.online,
            playit_auto: self.playit,
        };
        let job = CreateJob {
            log: Default::default(),
            progress: Default::default(),
            result: Default::default(),
        };
        let (log, progress, result) = (job.log.clone(), job.progress.clone(), job.result.clone());
        std::thread::spawn(move || {
            let l = |s: &str| log.lock().unwrap().push(s.to_string());
            let p = |a: u64, b: u64| *progress.lock().unwrap() = (a, b);
            let r = create::create_server(&opts, &l, &p).map_err(|e| format!("{e:#}"));
            *result.lock().unwrap() = Some(r);
        });
        self.error.clear();
        self.job = Some(job);
    }

    fn finished(&self) -> bool {
        self.job
            .as_ref()
            .is_some_and(|j| j.result.lock().unwrap().is_some())
    }

    fn show_job(&self, ui: &mut egui::Ui, job: &CreateJob, done: &mut Option<String>) {
        let result = job.result.lock().unwrap().clone();
        match &result {
            None => {
                ui.horizontal(|ui| {
                    ui.spinner();
                    ui.label(format!("Création de « {} »…", self.name.trim()));
                });
                let (a, b) = *job.progress.lock().unwrap();
                if b > 0 && a < b {
                    ui.add(egui::ProgressBar::new(a as f32 / b as f32).show_percentage());
                }
            }
            Some(Ok(_)) => {
                ui.colored_label(GREEN, "✔ Serveur prêt !");
            }
            Some(Err(e)) => {
                ui.colored_label(RED, format!("✖ {e}"));
            }
        }
        egui::ScrollArea::vertical()
            .max_height(220.0)
            .stick_to_bottom(true)
            .show(ui, |ui| {
                for l in job.log.lock().unwrap().iter() {
                    ui.label(RichText::new(l).monospace().small());
                }
            });
        if let Some(Ok(dir)) = &result {
            if ui.button("Ouvrir le serveur").clicked() {
                *done = dir.file_name().map(|n| n.to_string_lossy().to_string());
            }
        }
    }
}

impl PlayitDialog {
    fn start_link(&mut self) {
        let (code, url) = playit::new_claim();
        *self.url.lock().unwrap() = url.clone();
        *self.status.lock().unwrap() = "Ouverture du navigateur…".into();
        self.cancel.store(false, Ordering::Relaxed);
        self.busy.store(true, Ordering::Relaxed);
        let (status, cancel, busy) = (self.status.clone(), self.cancel.clone(), self.busy.clone());
        let _ = open::that(&url);
        std::thread::spawn(move || {
            let on_status = |s: &str| {
                *status.lock().unwrap() = match s {
                    "WaitingForUserVisit" => "En attente de la page Playit…",
                    "WaitingForUser" => "Validez la liaison dans le navigateur…",
                    "UserAccepted" => "Accepté, finalisation…",
                    other => other,
                }
                .to_string();
            };
            let r = playit::link(&code, &on_status, &cancel);
            *status.lock().unwrap() = match r {
                Ok(()) => String::new(),
                Err(e) => format!("✖ {}", playit::explain(&e)),
            };
            busy.store(false, Ordering::Relaxed);
        });
    }
}

fn status_dot(st: &Status) -> (&'static str, Color32) {
    if st.stopping || st.starting || (st.running && !st.ready) {
        ("●", ORANGE)
    } else if st.running {
        ("●", GREEN)
    } else {
        ("○", MUTED)
    }
}

fn status_text(st: &Status) -> &'static str {
    if st.stopping {
        "Arrêt en cours"
    } else if st.starting || (st.running && !st.ready) {
        "Démarrage…"
    } else if st.running {
        "En ligne"
    } else {
        "Arrêté"
    }
}

fn line_color(line: &str) -> Color32 {
    if line.contains("ERROR") || line.contains("Exception") || line.starts_with('✖') {
        RED
    } else if line.contains("WARN") {
        ORANGE
    } else if line.starts_with("──") || line.starts_with('>') || line.starts_with("Playit") {
        ACCENT
    } else {
        Color32::from_rgb(0xc9, 0xd1, 0xd9)
    }
}

fn fmt_uptime(d: Duration) -> String {
    let s = d.as_secs();
    match s {
        0..60 => format!("{s} s"),
        60..3600 => format!("{} min", s / 60),
        _ => format!("{} h {:02} min", s / 3600, (s % 3600) / 60),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn uptime_is_human() {
        assert_eq!(fmt_uptime(Duration::from_secs(42)), "42 s");
        assert_eq!(fmt_uptime(Duration::from_secs(3 * 60)), "3 min");
        assert_eq!(fmt_uptime(Duration::from_secs(3600 + 5 * 60)), "1 h 05 min");
    }
}
