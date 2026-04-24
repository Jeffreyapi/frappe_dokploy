# =============================================================================
#  Makefile — commandes de développement local pour frappe_dokploy
#  Usage : make <cible>
# =============================================================================

PYTHON   ?= python
SANDBOX  := _sandbox_test

.DEFAULT_GOAL := help

.PHONY: help tui test clean

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ── TUI interactif ────────────────────────────────────────────────────────────
tui: ## Lance le TUI dans un dossier sandbox ($(SANDBOX)/)
	@mkdir -p $(SANDBOX)
	@echo "→ Ouverture du TUI dans $(SANDBOX)/"
	@cd $(SANDBOX) && $(PYTHON) $(CURDIR)/scripts/fd.py

# ── Test headless ─────────────────────────────────────────────────────────────
test: ## Teste la logique copie+replace sans TUI (headless)
	@$(PYTHON) scripts/test_fd.py

# ── Nettoyage ─────────────────────────────────────────────────────────────────
clean: ## Supprime le dossier sandbox de test
	@rm -rf $(SANDBOX)
	@echo "  ✓ $(SANDBOX)/ supprimé"
