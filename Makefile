# ANKAVM development helpers.
#
# Usage:
#   make i18n          # refresh PAGE_STRINGS dicts from index.html
#   make i18n-check    # CI gate: fail if untranslated TR strings remain
#   make test          # pytest -q
#   make sbom          # CycloneDX SBOM into /var/lib/ankavm/sbom-cyclonedx.json
#   make security      # bandit + pip-audit
#   make clean         # drop transient files (__pycache__, tmp_i18n)

PYTHON ?= python3

.PHONY: i18n
i18n:
	$(PYTHON) scripts/i18n_pipeline.py

.PHONY: i18n-check
i18n-check:
	$(PYTHON) scripts/i18n_extract.py
	$(PYTHON) scripts/i18n_html_scan.py
	$(PYTHON) scripts/i18n_js_scan.py
	@if [ -s tmp_i18n/missing_html_tr.txt ] || [ -s tmp_i18n/missing_js_tr.txt ]; then \
		echo "i18n-check: untranslated TR strings detected — run 'make i18n'"; \
		exit 1; \
	fi

.PHONY: test
test:
	$(PYTHON) -m pytest -q

.PHONY: sbom
sbom:
	$(PYTHON) -c "from ankavm.backend import sbom_generator; \
import json; print(json.dumps(sbom_generator.generate(), indent=2))"

.PHONY: security
security:
	bandit -r ankavm/backend -ll -i || true
	pip-audit -r requirements.txt || true

.PHONY: clean
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf tmp_i18n
