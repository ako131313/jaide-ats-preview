/**
 * firm-pitch.js — JAIDE ATS Firm Pitch PDF Generator
 * Handles: modal lifecycle, firm/candidate autocomplete, option loading, submit → download
 */
(function () {
    "use strict";

    var _overlay = null;
    var _acFirm = null;
    var _acCand = null;

    // ── Helpers ────────────────────────────────────────────────────────────
    function _esc(s) {
        return String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function _$(id) { return document.getElementById(id); }

    function _show(id) { var el = _$(id); if (el) el.style.display = ""; }
    function _hide(id) { var el = _$(id); if (el) el.style.display = "none"; }
    function _val(id, v) {
        var el = _$(id);
        if (!el) return "";
        if (v !== undefined) { el.value = v; return v; }
        return el.value;
    }

    // ── Open / Close ────────────────────────────────────────────────────────
    /**
     * openFirmPitchModal(opts)
     * opts: {
     *   firm: { id, name }          — pre-fill the firm AC
     *   candidate: { id, name, practice_areas }  — pre-fill candidate AC
     * }
     */
    function openFirmPitchModal(opts) {
        opts = opts || {};
        _overlay = _$("firm-pitch-modal-overlay");
        if (!_overlay) return;

        // Reset form
        _resetForm();

        // Pre-fill firm
        if (opts.firm && opts.firm.name) {
            var firmItem = {
                fp_id: opts.firm.id || "",
                name: opts.firm.name,
                label: opts.firm.name,
                meta: opts.firm.meta || "",
            };
            if (_acFirm) {
                _acFirm.select(firmItem);
            } else {
                // AC not yet created; store and init will pick it up
                window._fpPendingFirm = firmItem;
            }
            _onFirmSelected(firmItem);
        }

        // Pre-fill candidate
        if (opts.candidate && opts.candidate.name) {
            var candItem = {
                id: opts.candidate.id || "",
                name: opts.candidate.name,
                label: opts.candidate.name,
                practice_areas: opts.candidate.practice_areas || "",
            };
            if (_acCand) {
                _acCand.select(candItem);
            } else {
                window._fpPendingCand = candItem;
            }
            _onCandSelected(candItem);
        }

        _overlay.classList.add("open");
    }

    function closeFirmPitchModal() {
        if (_overlay) _overlay.classList.remove("open");
    }

    function _resetForm() {
        if (_acFirm) _acFirm.clear();
        if (_acCand) _acCand.clear();
        _val("fp-firm-id", "");
        _val("fp-firm-name", "");
        _val("fp-cand-id", "");
        _hide("fp-firm-preview");
        _$("fp-firm-preview").textContent = "";

        // Reset selects
        var officeEl = _$("fp-office-select");
        var practiceEl = _$("fp-practice-select");
        if (officeEl) officeEl.innerHTML = '<option value="">All Offices</option>';
        if (practiceEl) practiceEl.innerHTML = '<option value="">All Practice Groups</option>';

        _val("fp-custom-prompt", "");
        var toneEl = _$("fp-tone");
        if (toneEl) toneEl.value = "professional";
        var anonEl = _$("fp-anonymize");
        if (anonEl) anonEl.checked = false;
        _val("fp-recruiter-name", "");
        _val("fp-recruiter-title", "");
        _val("fp-recruiter-contact", "");

        _hide("firm-pitch-loading");
        var submitBtn = _$("firm-pitch-submit");
        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Generate PDF"; }
    }

    // ── Firm selected ───────────────────────────────────────────────────────
    function _onFirmSelected(item) {
        _val("fp-firm-id", item.fp_id || "");
        _val("fp-firm-name", item.name || "");

        // Show preview
        var prev = _$("fp-firm-preview");
        if (prev) {
            var metaText = item.meta || "";
            if (metaText) {
                prev.textContent = metaText;
                _show("fp-firm-preview");
            } else {
                _hide("fp-firm-preview");
            }
        }

        // Load office + practice dropdowns
        var name = item.name || "";
        if (!name) return;
        fetch("/api/firm-pitch/options?firm_name=" + encodeURIComponent(name))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var officeEl = _$("fp-office-select");
                if (officeEl) {
                    officeEl.innerHTML = '<option value="">All Offices</option>';
                    (data.offices || []).forEach(function (o) {
                        var opt = document.createElement("option");
                        opt.value = o;
                        opt.textContent = o;
                        officeEl.appendChild(opt);
                    });
                }
                var practiceEl = _$("fp-practice-select");
                if (practiceEl) {
                    practiceEl.innerHTML = '<option value="">All Practice Groups</option>';
                    (data.practice_groups || []).forEach(function (p) {
                        var opt = document.createElement("option");
                        opt.value = p;
                        opt.textContent = p;
                        practiceEl.appendChild(opt);
                    });
                    // Auto-select candidate's practice area if already chosen
                    var candPractice = window._fpCandPractice || "";
                    if (candPractice) {
                        _autoSelectPractice(candPractice);
                    }
                }
            })
            .catch(function (e) { console.warn("[FirmPitch] options error:", e); });
    }

    // ── Candidate selected ──────────────────────────────────────────────────
    function _onCandSelected(item) {
        _val("fp-cand-id", item.id || "");
        window._fpCandPractice = item.practice_areas || "";
        // If practice dropdown already populated, auto-select
        _autoSelectPractice(window._fpCandPractice);
    }

    function _autoSelectPractice(candPractice) {
        if (!candPractice) return;
        var practiceEl = _$("fp-practice-select");
        if (!practiceEl || practiceEl.options.length <= 1) return;
        var cpLower = candPractice.toLowerCase();
        for (var i = 0; i < practiceEl.options.length; i++) {
            if (practiceEl.options[i].value.toLowerCase().indexOf(cpLower) !== -1 ||
                cpLower.indexOf(practiceEl.options[i].value.toLowerCase()) !== -1) {
                practiceEl.selectedIndex = i;
                break;
            }
        }
    }

    // ── Submit ──────────────────────────────────────────────────────────────
    function _onSubmit() {
        var firmName = _val("fp-firm-name");
        var firmId = _val("fp-firm-id");
        if (!firmName && !firmId) {
            alert("Please select a firm first.");
            return;
        }

        var payload = {
            firm_name: firmName,
            firm_fp_id: firmId || null,
            attorney_id: _val("fp-cand-id") || null,
            office: _val("fp-office-select") || null,
            practice_group: _val("fp-practice-select") || null,
            custom_prompt: _val("fp-custom-prompt"),
            tone: _val("fp-tone") || "professional",
            anonymize_candidate: !!(_$("fp-anonymize") && _$("fp-anonymize").checked),
            recruiter_name: _val("fp-recruiter-name"),
            recruiter_title: _val("fp-recruiter-title"),
            recruiter_contact: _val("fp-recruiter-contact"),
        };

        // Show loading
        _show("firm-pitch-loading");
        var submitBtn = _$("firm-pitch-submit");
        if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Generating…"; }

        fetch("/api/firm-pitch/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        })
            .then(function (r) {
                if (!r.ok) {
                    return r.json().then(function (j) {
                        throw new Error(j.error || "Server error " + r.status);
                    });
                }
                return r.blob();
            })
            .then(function (blob) {
                var url = URL.createObjectURL(blob);
                var a = document.createElement("a");
                a.href = url;
                a.download = "Firm_Pitch_" + (firmName || "Document").replace(/\s+/g, "_") + ".pdf";
                document.body.appendChild(a);
                a.click();
                setTimeout(function () {
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                }, 200);
                closeFirmPitchModal();
            })
            .catch(function (err) {
                console.error("[FirmPitch] generate error:", err);
                alert("Error generating firm pitch: " + err.message);
            })
            .finally(function () {
                _hide("firm-pitch-loading");
                if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Generate PDF"; }
            });
    }

    // ── Init ────────────────────────────────────────────────────────────────
    function _init() {
        // Wait for JAIDE._makeAC to be available (dashboard.js loads after us)
        function _setup() {
            var makeAC = window.JAIDE && window.JAIDE._makeAC;
            if (!makeAC) {
                setTimeout(_setup, 100);
                return;
            }

            _acFirm = makeAC(
                "fp-firm-input", "fp-firm-dropdown",
                "fp-firm-pill", "fp-firm-pill-label", "fp-firm-clear",
                function (q) {
                    return fetch("/api/search/firms?q=" + encodeURIComponent(q))
                        .then(function (r) { return r.json(); });
                },
                function (item) {
                    _onFirmSelected(item);
                }
            );

            _acCand = makeAC(
                "fp-cand-input", "fp-cand-dropdown",
                "fp-cand-pill", "fp-cand-pill-label", "fp-cand-clear",
                function (q) {
                    return fetch("/api/search/attorneys?q=" + encodeURIComponent(q))
                        .then(function (r) { return r.json(); });
                },
                function (item) {
                    _onCandSelected(item);
                }
            );

            // Apply any pending pre-fills
            if (window._fpPendingFirm) {
                _acFirm.select(window._fpPendingFirm);
                _onFirmSelected(window._fpPendingFirm);
                window._fpPendingFirm = null;
            }
            if (window._fpPendingCand) {
                _acCand.select(window._fpPendingCand);
                _onCandSelected(window._fpPendingCand);
                window._fpPendingCand = null;
            }

            // Wire buttons
            var closeBtn = _$("firm-pitch-close");
            if (closeBtn) closeBtn.addEventListener("click", closeFirmPitchModal);

            var cancelBtn = _$("firm-pitch-cancel");
            if (cancelBtn) cancelBtn.addEventListener("click", closeFirmPitchModal);

            var submitBtn = _$("firm-pitch-submit");
            if (submitBtn) submitBtn.addEventListener("click", _onSubmit);

            // Close on overlay backdrop click
            var overlay = _$("firm-pitch-modal-overlay");
            if (overlay) {
                overlay.addEventListener("click", function (e) {
                    if (e.target === overlay) closeFirmPitchModal();
                });
            }
        }

        _setup();

        // Export
        window.JAIDE = window.JAIDE || {};
        window.JAIDE.openFirmPitchModal = openFirmPitchModal;
    }

    // Boot on DOMContentLoaded
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", _init);
    } else {
        _init();
    }
})();
