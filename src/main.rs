//! ServerCraft Agent — édition Rust (préversion).
#![cfg_attr(windows, windows_subsystem = "windows")] // pas de console noire

mod backups;
mod create;
mod java;
mod launch;
mod loaders;
mod meta;
mod modrinth;
mod net;
mod paths;
mod playit;
mod process;
mod props;
mod ui;
mod voice;

fn main() -> eframe::Result {
    ui::run()
}
