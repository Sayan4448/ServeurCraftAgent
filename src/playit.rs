//! Tunnels Playit.gg automatiques. Port de app/core/playit.py : liaison du
//! compte (claim), création des tunnels via l'API, agent officiel lancé en
//! arrière-plan. Fonctions bloquantes : à appeler depuis un thread.
use anyhow::Result;
use std::path::Path;
use std::sync::atomic::AtomicBool;

#[derive(Clone, Debug, PartialEq)]
pub struct Tunnel {
    pub name: String,
    pub proto: String, // "tcp" | "udp"
    pub address: String,
    pub local: u16,
}

/// Étapes de setup_server, pour l'affichage.
#[derive(Clone, Debug)]
pub enum Event {
    Create { label: String, local: u16 },
    Ready { label: String, address: String },
    Agent,
}

pub fn linked() -> bool {
    todo!("agent playit")
}

/// (code, url à ouvrir dans le navigateur)
pub fn new_claim() -> (String, String) {
    todo!("agent playit")
}

/// Attend la validation dans le navigateur puis enregistre la clé.
/// `on_status` : WaitingForUserVisit / WaitingForUser / UserAccepted.
pub fn link(_code: &str, _on_status: &dyn Fn(&str), _cancel: &AtomicBool) -> Result<()> {
    todo!("agent playit")
}

pub fn unlink() {
    todo!("agent playit")
}

/// Tunnels créés / retrouvés pour ce serveur, enregistrés dans
/// servercraft.json (`tunnels`, `playit_auto`), adresse vocale écrite dans
/// le mod vocal, agent démarré.
pub fn setup_server(_name: &str, _dir: &Path, _log: &dyn Fn(Event)) -> Result<Vec<Tunnel>> {
    todo!("agent playit")
}

pub fn agent_running() -> bool {
    todo!("agent playit")
}

/// Dernière erreur de l'agent s'il s'est arrêté tout seul.
pub fn agent_error() -> String {
    todo!("agent playit")
}

pub fn stop_agent() {
    todo!("agent playit")
}

/// Message clair (français) pour une erreur Playit.
pub fn explain(e: &anyhow::Error) -> String {
    e.to_string()
}
