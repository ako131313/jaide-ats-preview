/**
 * custom.js — JAIDE ATS
 * Handles custom attorney/job/firm modals, tags, notes, and delete actions.
 */
(function () {
    'use strict';

    // ── Ensure window.JAIDE namespace ─────────────────────────────────────
    if (!window.JAIDE) window.JAIDE = { fn: {} };
    if (!window.JAIDE.fn) window.JAIDE.fn = {};

    // ── Toast helper (reuse global if available) ──────────────────────────
    function showToast(msg, type) {
        if (window.JAIDE && window.JAIDE.fn && window.JAIDE.fn.showToast) {
            window.JAIDE.fn.showToast(msg, type);
            return;
        }
        const c = document.getElementById('toast-container');
        if (!c) return;
        const t = document.createElement('div');
        t.className = 'toast toast-' + (type || 'success');
        t.textContent = msg;
        c.appendChild(t);
        setTimeout(() => t.remove(), 3500);
    }

    // ── Modal helpers ─────────────────────────────────────────────────────
    function openModal(id) {
        const el = document.getElementById(id);
        if (el) el.classList.add('open');
    }
    function closeModal(id) {
        const el = document.getElementById(id);
        if (el) el.classList.remove('open');
    }

    // ── Tab handling for custom attorney modal ────────────────────────────
    function initModalTabs(overlayId) {
        const overlay = document.getElementById(overlayId);
        if (!overlay) return;
        overlay.querySelectorAll('.modal-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tabId = btn.dataset.tab;
                overlay.querySelectorAll('.modal-tab-btn').forEach(b => b.classList.remove('active'));
                overlay.querySelectorAll('.modal-tab-panel').forEach(p => p.classList.remove('active'));
                btn.classList.add('active');
                const panel = overlay.querySelector('#' + tabId);
                if (panel) panel.classList.add('active');
            });
        });
    }

    // =========================================================================
    // Custom Attorney Modal
    // =========================================================================

    function openCustomAttorneyModal(attorney) {
        const isEdit = !!attorney;
        document.getElementById('custom-attorney-modal-title').textContent = isEdit ? 'Edit Candidate' : 'Add Candidate';
        document.getElementById('custom-attorney-id').value = isEdit ? attorney.id : '';

        // Reset all tabs to first
        const overlay = document.getElementById('custom-attorney-modal-overlay');
        overlay.querySelectorAll('.modal-tab-btn').forEach((b, i) => b.classList.toggle('active', i === 0));
        overlay.querySelectorAll('.modal-tab-panel').forEach((p, i) => p.classList.toggle('active', i === 0));

        // Fill form fields
        const f = attorney || {};
        document.getElementById('ca-first-name').value = f.first_name || '';
        document.getElementById('ca-last-name').value = f.last_name || '';
        document.getElementById('ca-email').value = f.email || '';
        document.getElementById('ca-phone').value = f.phone || '';
        document.getElementById('ca-current-firm').value = f.current_firm || '';
        document.getElementById('ca-title').value = f.title || '';
        document.getElementById('ca-location-city').value = f.location_city || '';
        document.getElementById('ca-location-state').value = f.location_state || '';
        document.getElementById('ca-gender').value = f.gender || '';
        document.getElementById('ca-diverse').value = f.diverse || '';
        document.getElementById('ca-graduation-year').value = f.graduation_year || '';
        document.getElementById('ca-law-school').value = f.law_school || '';
        document.getElementById('ca-undergraduate').value = f.undergraduate || '';
        document.getElementById('ca-llm-school').value = f.llm_school || '';
        document.getElementById('ca-llm-specialty').value = f.llm_specialty || '';
        document.getElementById('ca-bar-admissions').value = f.bar_admissions || '';
        document.getElementById('ca-practice-areas').value = f.practice_areas || '';
        document.getElementById('ca-specialty').value = f.specialty || '';
        document.getElementById('ca-linkedin-url').value = f.linkedin_url || '';
        document.getElementById('ca-bio').value = f.bio || '';
        document.getElementById('ca-prior-experience').value = f.prior_experience || '';
        document.getElementById('ca-clerkships').value = f.clerkships || '';
        document.getElementById('ca-languages').value = f.languages || '';
        document.getElementById('ca-source-notes').value = f.source_notes || '';
        document.getElementById('ca-tags').value = f.tags || '';

        document.getElementById('custom-attorney-status').textContent = '';
        openModal('custom-attorney-modal-overlay');
    }

    function closeCustomAttorneyModal() {
        closeModal('custom-attorney-modal-overlay');
    }

    // Populate firm datalist for attorney modal
    function populateFirmDatalist() {
        fetch('/api/custom/firms')
            .then(r => r.json())
            .then(data => {
                const dl = document.getElementById('ca-firm-datalist');
                if (!dl) return;
                dl.innerHTML = (data.firms || []).map(f => `<option value="${f.name}">`).join('');
            })
            .catch(() => {});
    }

    document.addEventListener('DOMContentLoaded', function () {
        initModalTabs('custom-attorney-modal-overlay');

        // Open from "+ Add Candidate" button
        const btnAdd = document.getElementById('btn-add-custom-attorney');
        if (btnAdd) btnAdd.addEventListener('click', () => {
            populateFirmDatalist();
            openCustomAttorneyModal(null);
        });

        // Close buttons
        const closeBtn = document.getElementById('custom-attorney-modal-close');
        if (closeBtn) closeBtn.addEventListener('click', closeCustomAttorneyModal);
        const cancelBtn = document.getElementById('custom-attorney-cancel');
        if (cancelBtn) cancelBtn.addEventListener('click', closeCustomAttorneyModal);

        // Form submit
        const form = document.getElementById('custom-attorney-form');
        if (form) form.addEventListener('submit', async function (e) {
            e.preventDefault();
            const id = document.getElementById('custom-attorney-id').value;
            const payload = {
                first_name: document.getElementById('ca-first-name').value.trim(),
                last_name: document.getElementById('ca-last-name').value.trim(),
                email: document.getElementById('ca-email').value.trim(),
                phone: document.getElementById('ca-phone').value.trim(),
                current_firm: document.getElementById('ca-current-firm').value.trim(),
                title: document.getElementById('ca-title').value,
                location_city: document.getElementById('ca-location-city').value.trim(),
                location_state: document.getElementById('ca-location-state').value.trim(),
                gender: document.getElementById('ca-gender').value,
                diverse: document.getElementById('ca-diverse').value,
                graduation_year: parseInt(document.getElementById('ca-graduation-year').value) || null,
                law_school: document.getElementById('ca-law-school').value.trim(),
                undergraduate: document.getElementById('ca-undergraduate').value.trim(),
                llm_school: document.getElementById('ca-llm-school').value.trim(),
                llm_specialty: document.getElementById('ca-llm-specialty').value.trim(),
                bar_admissions: document.getElementById('ca-bar-admissions').value.trim(),
                practice_areas: document.getElementById('ca-practice-areas').value.trim(),
                specialty: document.getElementById('ca-specialty').value.trim(),
                linkedin_url: document.getElementById('ca-linkedin-url').value.trim(),
                bio: document.getElementById('ca-bio').value.trim(),
                prior_experience: document.getElementById('ca-prior-experience').value.trim(),
                clerkships: document.getElementById('ca-clerkships').value.trim(),
                languages: document.getElementById('ca-languages').value.trim(),
                source_notes: document.getElementById('ca-source-notes').value.trim(),
                tags: document.getElementById('ca-tags').value.trim(),
            };
            const statusEl = document.getElementById('custom-attorney-status');
            statusEl.textContent = 'Saving...';
            try {
                const url = id ? `/api/custom/attorneys/${id}` : '/api/custom/attorneys';
                const method = id ? 'PUT' : 'POST';
                const resp = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const result = await resp.json();
                if (!resp.ok || result.error) throw new Error(result.error || 'Save failed');

                // Upload resume if selected
                const resumeFile = document.getElementById('ca-resume').files[0];
                const savedId = result.id || id;
                if (resumeFile && savedId) {
                    const fd = new FormData();
                    fd.append('resume', resumeFile);
                    await fetch(`/api/custom/attorneys/${savedId}/resume`, { method: 'POST', body: fd });
                }

                closeCustomAttorneyModal();
                showToast(id ? 'Candidate updated.' : 'Candidate added.', 'success');
                // Notify other modules to refresh
                window.dispatchEvent(new CustomEvent('customRecordSaved', { detail: { type: 'attorney', id: savedId } }));
            } catch (err) {
                statusEl.textContent = err.message || 'Save failed.';
            }
        });
    });

    // =========================================================================
    // Custom Job Modal
    // =========================================================================

    function openCustomJobModal(job) {
        const isEdit = !!job;
        document.getElementById('custom-job-modal-title').textContent = isEdit ? 'Edit Job' : 'Add Job';
        document.getElementById('custom-job-id').value = isEdit ? job.id : '';

        const f = job || {};
        document.getElementById('cj-firm-name').value = f.firm_name || '';
        document.getElementById('cj-job-title').value = f.job_title || '';
        document.getElementById('cj-job-description').value = f.job_description || '';
        document.getElementById('cj-location').value = f.location || '';
        document.getElementById('cj-status').value = f.status || 'Open';
        document.getElementById('cj-practice-areas').value = f.practice_areas || '';
        document.getElementById('cj-specialty').value = f.specialty || '';
        document.getElementById('cj-min-years').value = f.min_years || '';
        document.getElementById('cj-max-years').value = f.max_years || '';
        document.getElementById('cj-salary-min').value = f.salary_min || '';
        document.getElementById('cj-salary-max').value = f.salary_max || '';
        document.getElementById('cj-bar-required').value = f.bar_required || '';
        document.getElementById('cj-confidential').checked = !!f.confidential;
        document.getElementById('cj-contact-name').value = f.contact_name || '';
        document.getElementById('cj-contact-email').value = f.contact_email || '';
        document.getElementById('cj-contact-phone').value = f.contact_phone || '';
        document.getElementById('cj-notes').value = f.notes || '';
        document.getElementById('custom-job-status').textContent = '';

        // Populate firm datalist
        fetch('/api/custom/firms')
            .then(r => r.json())
            .then(data => {
                const dl = document.getElementById('cj-firm-datalist');
                if (!dl) return;
                dl.innerHTML = (data.firms || []).map(f => `<option value="${f.name}">`).join('');
            })
            .catch(() => {});

        openModal('custom-job-modal-overlay');
    }

    function closeCustomJobModal() {
        closeModal('custom-job-modal-overlay');
    }

    document.addEventListener('DOMContentLoaded', function () {
        const btnAddJob = document.getElementById('btn-add-custom-job');
        if (btnAddJob) btnAddJob.addEventListener('click', () => openCustomJobModal(null));

        const closeBtn = document.getElementById('custom-job-modal-close');
        if (closeBtn) closeBtn.addEventListener('click', closeCustomJobModal);
        const cancelBtn = document.getElementById('custom-job-cancel');
        if (cancelBtn) cancelBtn.addEventListener('click', closeCustomJobModal);

        const form = document.getElementById('custom-job-form');
        if (form) form.addEventListener('submit', async function (e) {
            e.preventDefault();
            const id = document.getElementById('custom-job-id').value;
            const payload = {
                firm_name: document.getElementById('cj-firm-name').value.trim(),
                job_title: document.getElementById('cj-job-title').value.trim(),
                job_description: document.getElementById('cj-job-description').value.trim(),
                location: document.getElementById('cj-location').value.trim(),
                status: document.getElementById('cj-status').value,
                practice_areas: document.getElementById('cj-practice-areas').value.trim(),
                specialty: document.getElementById('cj-specialty').value.trim(),
                min_years: parseInt(document.getElementById('cj-min-years').value) || null,
                max_years: parseInt(document.getElementById('cj-max-years').value) || null,
                salary_min: parseInt(document.getElementById('cj-salary-min').value) || null,
                salary_max: parseInt(document.getElementById('cj-salary-max').value) || null,
                bar_required: document.getElementById('cj-bar-required').value.trim(),
                confidential: document.getElementById('cj-confidential').checked ? 1 : 0,
                contact_name: document.getElementById('cj-contact-name').value.trim(),
                contact_email: document.getElementById('cj-contact-email').value.trim(),
                contact_phone: document.getElementById('cj-contact-phone').value.trim(),
                notes: document.getElementById('cj-notes').value.trim(),
            };
            const statusEl = document.getElementById('custom-job-status');
            statusEl.textContent = 'Saving...';
            try {
                const url = id ? `/api/custom/jobs/${id}` : '/api/custom/jobs';
                const method = id ? 'PUT' : 'POST';
                const resp = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const result = await resp.json();
                if (!resp.ok || result.error) throw new Error(result.error || 'Save failed');
                closeCustomJobModal();
                showToast(id ? 'Job updated.' : 'Job added.', 'success');
                window.dispatchEvent(new CustomEvent('customRecordSaved', { detail: { type: 'job', id: result.id || id } }));
            } catch (err) {
                statusEl.textContent = err.message || 'Save failed.';
            }
        });
    });

    // =========================================================================
    // Custom Firm Modal
    // =========================================================================

    function openCustomFirmModal(firm) {
        const isEdit = !!firm;
        document.getElementById('custom-firm-modal-title').textContent = isEdit ? 'Edit Firm' : 'Add Firm';
        document.getElementById('custom-firm-id').value = isEdit ? firm.id : '';

        const f = firm || {};
        document.getElementById('cf-name').value = f.name || '';
        document.getElementById('cf-website').value = f.website || '';
        document.getElementById('cf-total-attorneys').value = f.total_attorneys || '';
        document.getElementById('cf-partners').value = f.partners || '';
        document.getElementById('cf-counsel').value = f.counsel || '';
        document.getElementById('cf-associates').value = f.associates || '';
        document.getElementById('cf-office-locations').value = f.office_locations || '';
        document.getElementById('cf-practice-areas').value = f.practice_areas || '';
        document.getElementById('cf-ppp').value = f.ppp || '';
        document.getElementById('cf-vault-ranking').value = f.vault_ranking || '';
        document.getElementById('cf-firm-type').value = f.firm_type || '';
        document.getElementById('cf-notes').value = f.notes || '';
        document.getElementById('custom-firm-status').textContent = '';

        openModal('custom-firm-modal-overlay');
    }

    function closeCustomFirmModal() {
        closeModal('custom-firm-modal-overlay');
    }

    document.addEventListener('DOMContentLoaded', function () {
        const btnAddFirm = document.getElementById('btn-add-custom-firm');
        if (btnAddFirm) btnAddFirm.addEventListener('click', () => openCustomFirmModal(null));

        const closeBtn = document.getElementById('custom-firm-modal-close');
        if (closeBtn) closeBtn.addEventListener('click', closeCustomFirmModal);
        const cancelBtn = document.getElementById('custom-firm-cancel');
        if (cancelBtn) cancelBtn.addEventListener('click', closeCustomFirmModal);

        const form = document.getElementById('custom-firm-form');
        if (form) form.addEventListener('submit', async function (e) {
            e.preventDefault();
            const id = document.getElementById('custom-firm-id').value;
            const payload = {
                name: document.getElementById('cf-name').value.trim(),
                website: document.getElementById('cf-website').value.trim(),
                total_attorneys: parseInt(document.getElementById('cf-total-attorneys').value) || null,
                partners: parseInt(document.getElementById('cf-partners').value) || null,
                counsel: parseInt(document.getElementById('cf-counsel').value) || null,
                associates: parseInt(document.getElementById('cf-associates').value) || null,
                office_locations: document.getElementById('cf-office-locations').value.trim(),
                practice_areas: document.getElementById('cf-practice-areas').value.trim(),
                ppp: parseInt(document.getElementById('cf-ppp').value) || null,
                vault_ranking: parseInt(document.getElementById('cf-vault-ranking').value) || null,
                firm_type: document.getElementById('cf-firm-type').value,
                notes: document.getElementById('cf-notes').value.trim(),
            };
            const statusEl = document.getElementById('custom-firm-status');
            statusEl.textContent = 'Saving...';
            try {
                const url = id ? `/api/custom/firms/${id}` : '/api/custom/firms';
                const method = id ? 'PUT' : 'POST';
                const resp = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const result = await resp.json();
                if (!resp.ok || result.error) throw new Error(result.error || 'Save failed');
                closeCustomFirmModal();
                showToast(id ? 'Firm updated.' : 'Firm added.', 'success');
                window.dispatchEvent(new CustomEvent('customRecordSaved', { detail: { type: 'firm', id: result.id || id } }));
            } catch (err) {
                statusEl.textContent = err.message || 'Save failed.';
            }
        });
    });

    // =========================================================================
    // Delete custom record
    // =========================================================================

    async function deleteCustomRecord(type, id, name) {
        if (!confirm(`Delete ${name}? This will also remove them from any active pipelines.`)) return;
        try {
            const resp = await fetch(`/api/custom/${type}/${id}`, { method: 'DELETE' });
            const result = await resp.json();
            if (!resp.ok || result.error) throw new Error(result.error || 'Delete failed');
            showToast(`${name} deleted.`, 'success');
            window.dispatchEvent(new CustomEvent('customRecordDeleted', { detail: { type, id } }));
        } catch (err) {
            showToast(err.message || 'Delete failed.', 'error');
        }
    }

    // =========================================================================
    // Tags Popover
    // =========================================================================

    let _tagsCtx = null; // { recordType, recordSource, recordId }

    function openTagsPopover(recordType, recordSource, recordId, anchorEl) {
        _tagsCtx = { recordType, recordSource, recordId };
        const popover = document.getElementById('tags-popover');
        if (!popover) return;

        loadTags(recordType, recordSource, recordId);

        // Position near anchor
        if (anchorEl) {
            const rect = anchorEl.getBoundingClientRect();
            popover.style.top = (rect.bottom + window.scrollY + 4) + 'px';
            popover.style.left = Math.min(rect.left + window.scrollX, window.innerWidth - 320) + 'px';
        }
        popover.style.display = 'block';

        // Close on outside click
        setTimeout(() => {
            document.addEventListener('click', _closePopoverOnOutside, { once: true });
        }, 10);
    }

    function _closePopoverOnOutside(e) {
        const popover = document.getElementById('tags-popover');
        if (popover && !popover.contains(e.target)) {
            popover.style.display = 'none';
        }
    }

    function loadTags(recordType, recordSource, recordId) {
        fetch(`/api/records/${recordType}/${recordSource}/${recordId}/tags`)
            .then(r => r.json())
            .then(data => renderTagsList(data.tags || []))
            .catch(() => {});
    }

    function renderTagsList(tags) {
        const list = document.getElementById('tags-popover-list');
        if (!list) return;
        list.innerHTML = tags.map(t => `
            <span class="tag-pill">
                ${t.tag}
                <button class="tag-pill-remove" data-tag-id="${t.id}" title="Remove">&times;</button>
            </span>
        `).join('') || '<span style="font-size:12px;color:#696969">No tags yet</span>';

        list.querySelectorAll('.tag-pill-remove').forEach(btn => {
            btn.addEventListener('click', async () => {
                const tagId = btn.dataset.tagId;
                await fetch(`/api/records/${_tagsCtx.recordType}/${_tagsCtx.recordSource}/${_tagsCtx.recordId}/tags/${tagId}`, { method: 'DELETE' });
                loadTags(_tagsCtx.recordType, _tagsCtx.recordSource, _tagsCtx.recordId);
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        const addBtn = document.getElementById('tags-popover-add');
        const input = document.getElementById('tags-popover-input');
        if (!addBtn || !input) return;

        async function doAddTag() {
            const tag = input.value.trim();
            if (!tag || !_tagsCtx) return;
            await fetch(`/api/records/${_tagsCtx.recordType}/${_tagsCtx.recordSource}/${_tagsCtx.recordId}/tags`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tag }),
            });
            input.value = '';
            loadTags(_tagsCtx.recordType, _tagsCtx.recordSource, _tagsCtx.recordId);
        }

        addBtn.addEventListener('click', doAddTag);
        input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); doAddTag(); } });
    });

    // =========================================================================
    // Notes section (render into a container element)
    // =========================================================================

    function renderNotesSection(containerId, recordType, recordSource, recordId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        container.innerHTML = '<div class="notes-section"><div class="notes-section-title">Notes</div><div id="' + containerId + '-notes-list"></div><div class="notes-add-row"><textarea placeholder="Add a note..." id="' + containerId + '-note-input"></textarea><button class="btn-primary btn-sm" id="' + containerId + '-note-add">Add</button></div></div>';

        function refreshNotes() {
            fetch(`/api/records/${recordType}/${recordSource}/${recordId}/notes`)
                .then(r => r.json())
                .then(data => {
                    const list = document.getElementById(containerId + '-notes-list');
                    if (!list) return;
                    list.innerHTML = (data.notes || []).map(n => `
                        <div class="note-item">
                            <div class="note-item-text">${escHtml(n.note_text)}</div>
                            <div class="note-item-meta">${n.created_at || ''}</div>
                            <button class="note-item-delete" data-note-id="${n.id}" title="Delete">&times;</button>
                        </div>
                    `).join('') || '<p style="font-size:13px;color:#696969">No notes yet.</p>';
                    list.querySelectorAll('.note-item-delete').forEach(btn => {
                        btn.addEventListener('click', async () => {
                            await fetch(`/api/records/${recordType}/${recordSource}/${recordId}/notes/${btn.dataset.noteId}`, { method: 'DELETE' });
                            refreshNotes();
                        });
                    });
                });
        }

        const addBtn = document.getElementById(containerId + '-note-add');
        const noteInput = document.getElementById(containerId + '-note-input');
        if (addBtn && noteInput) {
            addBtn.addEventListener('click', async () => {
                const text = noteInput.value.trim();
                if (!text) return;
                await fetch(`/api/records/${recordType}/${recordSource}/${recordId}/notes`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ note_text: text }),
                });
                noteInput.value = '';
                refreshNotes();
            });
        }
        refreshNotes();
    }

    function escHtml(str) {
        return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // =========================================================================
    // Source filter wiring (attorney, jobs, firms)
    // =========================================================================

    document.addEventListener('DOMContentLoaded', function () {
        // Generic source filter click handler
        document.querySelectorAll('.source-filter').forEach(filterEl => {
            filterEl.querySelectorAll('.source-filter-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    filterEl.querySelectorAll('.source-filter-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    // Dispatch a custom event for other modules to respond
                    filterEl.dispatchEvent(new CustomEvent('sourceFilterChange', {
                        bubbles: true,
                        detail: { source: btn.dataset.src, filterId: filterEl.id }
                    }));
                });
            });
        });
    });

    // =========================================================================
    // Exports
    // =========================================================================
    window.JAIDE.openCustomAttorneyModal = openCustomAttorneyModal;
    window.JAIDE.openCustomJobModal = openCustomJobModal;
    window.JAIDE.openCustomFirmModal = openCustomFirmModal;
    window.JAIDE.openTagsPopover = openTagsPopover;
    window.JAIDE.renderNotesSection = renderNotesSection;
    window.JAIDE.deleteCustomRecord = deleteCustomRecord;

})();
