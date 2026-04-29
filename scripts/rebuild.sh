#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
#  rebuild.sh — relance l'environnement de développement Frappe
#
#  Usage (depuis la racine du repo projet) :
#    bash frappe_deploy/scripts/rebuild.sh            # relance idempotente
#    bash frappe_deploy/scripts/rebuild.sh --reset    # repart de zéro
#
#  Mode normal  : relance devcontainer-setup.sh — saute les étapes déjà faites.
#                 Utile après un setup raté ou pour appliquer un bump submodule.
#
#  Mode --reset : supprime ~/frappe-bench et le site avant de relancer.
#                 Utile quand le bench est corrompu ou après un changement majeur.
#
#  Le script pull toujours le dernier commit de frappe_deploy avant de lancer
#  le setup, pour garantir d'utiliser la version la plus récente.
# =============================================================================

RESET=0
for arg in "$@"; do
  [ "$arg" = "--reset" ] && RESET=1
done

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[rebuild $(date +'%T')] $*"; }
ok()   { echo "[rebuild $(date +'%T')] ✓ $*"; }
warn() { echo "[rebuild $(date +'%T')] ⚠ $*"; }

PROJECT_ROOT="${PWD}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH_DIR="$HOME/frappe-bench"

# ── Vérification : lancer depuis la racine du repo projet ─────────────────────
if [ ! -d "$PROJECT_ROOT/frappe_deploy" ]; then
  echo "ERREUR : lancer depuis la racine du repo projet (où frappe_deploy/ existe)."
  echo "  cd /workspaces/<app_name> && bash frappe_deploy/scripts/rebuild.sh"
  exit 1
fi

# ── Mise à jour du submodule frappe_deploy ────────────────────────────────────
log "Mise à jour du submodule frappe_deploy..."
if git -C "$PROJECT_ROOT" submodule update --init frappe_deploy 2>/dev/null; then
  # Tenter un pull pour avoir le dernier commit si on est en mode détaché
  git -C "$PROJECT_ROOT/frappe_deploy" fetch origin main --quiet 2>/dev/null || true
  ok "frappe_deploy à jour"
else
  warn "Impossible de mettre à jour frappe_deploy — utilisation de la version locale"
fi

# ── Mode reset ────────────────────────────────────────────────────────────────
if [ "$RESET" -eq 1 ]; then
  echo ""
  warn "══════════════════════════════════════════════════════════"
  warn "  MODE RESET — suppression de $BENCH_DIR"
  warn "  Les données du site seront PERDUES."
  warn "══════════════════════════════════════════════════════════"
  echo ""
  read -rp "  Confirmer ? [oui/NON] : " _confirm
  if [ "$_confirm" != "oui" ]; then
    echo "  Annulé."
    exit 0
  fi

  log "Suppression de $BENCH_DIR..."
  # Déréférencer les symlinks d'apps avant de supprimer (évite rm -rf sur le workspace)
  if [ -d "$BENCH_DIR/apps" ]; then
    for link in "$BENCH_DIR/apps"/*/; do
      [ -L "${link%/}" ] && rm "${link%/}"
    done
  fi
  rm -rf "$BENCH_DIR"
  ok "Bench supprimé"
fi

# ── Relancer le setup ─────────────────────────────────────────────────────────
echo ""
log "Lancement de devcontainer-setup.sh..."
echo ""
bash "$SCRIPT_DIR/devcontainer-setup.sh"
