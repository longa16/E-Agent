/*  État  */
let allEmails = [];
let currentEmail = null;
let activeFilter = 'all';
let currentUserEmail = '';

const $ = id => document.getElementById(id);
const el = tag => document.createElement(tag);

/* Formatage */
function esc(s) { return (s || '').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function initials(name) {
    return (name || '?').trim().split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase();
}

function avatarBg(name) {
    const palette = [
        '#c2622e', '#2563eb', '#7c3aed', '#059669',
        '#b45309', '#0891b2', '#9333ea', '#16a34a',
    ];
    let h = 0;
    for (const c of (name || '')) h = (h * 31 + c.charCodeAt(0)) % palette.length;
    return palette[h];
}

function relDate(str) {
    try {
        const diff = Date.now() - new Date(str).getTime();
        const m = Math.floor(diff / 60000);
        if (m < 1) return 'maintenant';
        if (m < 60) return `${m} min`;
        const h = Math.floor(m / 60);
        if (h < 24) return `${h}h`;
        return new Date(str).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
    } catch { return str || ''; }
}

/*  Chips  */
const PRIORITY_LABEL = { high: 'Urgent', medium: 'Priorité moyenne', low: 'Faible priorité' };
const CATEGORY_LABEL = {
    important: 'Important', reply_needed: 'À répondre',
    newsletter: 'Newsletter', notification: 'Notification',
    spam: 'Spam', promotional: 'Promo',
};

function priorityChip(p) {
    if (!p) return '';
    const cls = p === 'high' ? 'chip-hi' : p === 'medium' ? 'chip-mid' : 'chip-lo';
    return `<span class="chip ${cls}">${PRIORITY_LABEL[p] || p}</span>`;
}

function categoryChip(c) {
    if (!c) return '';
    return `<span class="chip chip-cat">${CATEGORY_LABEL[c] || c}</span>`;
}

/* Toast */
let _toastTimer;
function toast(msg, type = '') {
    const t = $('toast');
    t.textContent = msg;
    t.className = `toast ${type}`;
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => t.classList.add('hidden'), 3500);
}

/* Auth */

async function checkAuth() {
    const loginScreen = $('login-screen');
    const sidebar = $('app-sidebar');
    const pane = $('app-pane');
    const loading = $('login-loading');
    const loginCard = loginScreen.querySelector('.login-card');

    // Show loading state
    loginCard.classList.add('hidden');
    loading.classList.remove('hidden');

    try {
        const r = await fetch('/auth/status');
        const data = await r.json();

        if (data.authenticated) {
            currentUserEmail = data.email || '';
            $('user-email-label').textContent = currentUserEmail;

            // Hide login, show app
            loginScreen.classList.add('hidden');
            sidebar.classList.remove('hidden');
            pane.classList.remove('hidden');

            // Load emails
            loadEmails();
        } else {
            // Show login screen
            loginCard.classList.remove('hidden');
            loading.classList.add('hidden');
            loginScreen.classList.remove('hidden');
            sidebar.classList.add('hidden');
            pane.classList.add('hidden');
        }
    } catch (e) {
        // Network error show login
        loginCard.classList.remove('hidden');
        loading.classList.add('hidden');
    }
}

function showUserInfo() {
    if (currentUserEmail) {
        toast(`Connecté : ${currentUserEmail}`, 'success');
    }
}

/* Chargement emails  */
let _loadRetryCount = 0;
const MAX_CLIENT_RETRIES = 2;

async function loadEmails(withAI = false) {
    $('email-list').innerHTML = `<div class="list-state"><div class="spin"></div>${withAI ? 'Analyse IA…' : 'Chargement…'}</div>`;
    try {
        const r = await fetch(`/emails?max_results=20${withAI ? '&process=true' : ''}`);
        if (r.status === 401) {
            // Session expired redirect to login
            window.location.href = '/auth/logout';
            return;
        }
        if (!r.ok) throw new Error(`Erreur ${r.status}`);
        const data = await r.json();
        allEmails = data.emails || [];
        _loadRetryCount = 0; // reset on success
        renderList(allEmails);
        if (withAI) toast(`${allEmails.length} emails analysés`, 'success');
    } catch (e) {
        _loadRetryCount++;
        if (_loadRetryCount <= MAX_CLIENT_RETRIES) {
            // Auto-retry after a short delay
            toast(`Erreur de chargement, nouvelle tentative (${_loadRetryCount}/${MAX_CLIENT_RETRIES})…`, 'error');
            setTimeout(() => loadEmails(withAI), 2000 * _loadRetryCount);
        } else {
            _loadRetryCount = 0;
            $('email-list').innerHTML = `<div class="list-state" style="color:#dc2626">
                <div style="margin-bottom:8px">⚠️ ${e.message}</div>
                <button onclick="loadEmails(false)" style="
                    padding:6px 16px;border-radius:8px;border:1px solid #444;
                    background:#232323;color:#fff;cursor:pointer;font-size:13px;
                ">Réessayer</button>
            </div>`;
            toast(e.message, 'error');
        }
    }
}

/* Rendu liste */
function renderList(emails) {
    if (!emails.length) {
        $('email-list').innerHTML = `<div class="list-state">Aucun email</div>`;
        return;
    }
    $('email-list').innerHTML = emails.map(e => `
    <div class="email-card ${e.is_read ? '' : 'unread'}" id="card-${e.id}" onclick="openEmail('${e.id}')">
      <div class="c-top">
        <span class="c-sender">${e.is_read ? '' : ' <span class="c-dot"></span>'} ${esc(e.sender_name || e.sender_email)}</span>
        <span class="c-date">${relDate(e.date)}</span>
      </div>
      <div class="c-subject">${esc(e.subject || '(sans objet)')}</div>
      <div class="c-snippet">${esc(e.snippet)}</div>
    </div>
  `).join('');
}

/* Filtres */
function setFilter(btn, filter) {
    document.querySelectorAll('.filter').forEach(f => f.classList.remove('active'));
    btn.classList.add('active');
    activeFilter = filter;
    applyFilters();
}

function filterEmails(q) { applyFilters(q); }

function applyFilters(q = $('search-input').value) {
    let list = [...allEmails];
    if (activeFilter === 'UNREAD') list = list.filter(e => !e.is_read);
    if (activeFilter === 'reply_needed') list = list.filter(e => e.category === 'reply_needed');
    if (activeFilter === 'important') list = list.filter(e => e.priority === 'high' || e.category === 'important');
    if (q.trim()) {
        const s = q.toLowerCase();
        list = list.filter(e =>
            (e.subject || '').toLowerCase().includes(s) ||
            (e.sender_name || '').toLowerCase().includes(s) ||
            (e.snippet || '').toLowerCase().includes(s)
        );
    }
    renderList(list);
}

/* Ouverture email */
async function openEmail(id) {
    document.querySelectorAll('.email-card').forEach(c => c.classList.remove('active'));
    const card = $(`card-${id}`);
    if (card) card.classList.add('active');

    $('empty-state').classList.add('hidden');
    $('email-detail').classList.remove('hidden');

    // Reset
    $('detail-subject').textContent = 'Chargement…';
    $('detail-sender').textContent = '';
    $('detail-email').textContent = '';
    $('detail-date').textContent = '';
    $('detail-body').textContent = '';
    $('detail-tags').innerHTML = '';
    $('ai-summary').textContent = 'Analyse en cours…';
    $('ai-classification').innerHTML = '';
    $('ai-loading').classList.remove('hidden');
    $('reply-textarea').value = '';
    $('btn-speak').disabled = true;

    // Retry logic for email detail
    let lastErr = null;
    for (let attempt = 0; attempt < 2; attempt++) {
        try {
            const r = await fetch(`/emails/${id}?summarize=true`);
            if (r.status === 401) { window.location.href = '/auth/logout'; return; }
            if (!r.ok) {
                const errData = await r.json().catch(() => ({}));
                throw new Error(errData.detail || `Erreur ${r.status}`);
            }
            const data = await r.json();
            currentEmail = data.email;
            render(data);

            // Marquer comme lu localement
            const cached = allEmails.find(e => e.id === id);
            if (cached) { cached.is_read = true; if (card) card.classList.remove('unread'); }
            return; // success, exit
        } catch (e) {
            lastErr = e;
            if (attempt === 0) {
                // Wait and retry once
                await new Promise(r => setTimeout(r, 1500));
            }
        }
    }
    // All retries failed
    $('detail-subject').textContent = 'Erreur de chargement';
    $('ai-loading').classList.add('hidden');
    $('ai-summary').textContent = lastErr.message;
    $('detail-body').innerHTML = `<button onclick="openEmail('${id}')" style="
        padding:6px 16px;border-radius:8px;border:1px solid #444;
        background:#232323;color:#fff;cursor:pointer;font-size:13px;margin-top:12px;
    ">Réessayer l'analyse</button>`;
    toast(lastErr.message, 'error');
}

/* Rendu détail */
function render(data) {
    const email = data.email;
    const cls = data.classification || {};

    const av = $('detail-avatar');
    av.textContent = initials(email.sender_name);
    av.style.background = avatarBg(email.sender_name);

    $('detail-subject').textContent = email.subject || '(sans objet)';
    $('detail-sender').textContent = email.sender_name || email.sender_email;
    $('detail-email').textContent = email.sender_email;
    $('detail-date').textContent = relDate(email.date);
    $('detail-body').textContent = email.body || email.snippet || '';

    const chips = [];
    if (!email.is_read) chips.push('<span class="chip chip-unread">Non lu</span>');
    if (cls.priority) chips.push(priorityChip(cls.priority));
    if (cls.category) chips.push(categoryChip(cls.category));
    $('detail-tags').innerHTML = chips.join('');

    $('ai-loading').classList.add('hidden');
    $('ai-summary').textContent = data.summary || 'Résumé non disponible.';

    const aiChips = [];
    if (cls.priority) aiChips.push(priorityChip(cls.priority));
    if (cls.category) aiChips.push(categoryChip(cls.category));
    if (cls.reason) aiChips.push(`<span style="font-size:11px;color:#888">${esc(cls.reason)}</span>`);
    $('ai-classification').innerHTML = aiChips.join('');

    $('btn-speak').disabled = false;
}

/*  Générer brouillon  */
async function generateDraft() {
    if (!currentEmail) return;
    const btn = $('btn-draft');
    btn.disabled = true;
    btn.textContent = 'Génération…';
    $('reply-textarea').value = '';
    $('reply-textarea').placeholder = 'L\'IA rédige une réponse…';

    try {
        const r = await fetch(`/emails/${currentEmail.id}/draft-reply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instructions: '' }),
        });
        if (r.status === 401) { window.location.href = '/auth/logout'; return; }
        if (!r.ok) throw new Error(`Erreur ${r.status}`);
        const data = await r.json();
        $('reply-textarea').value = data.draft || '';
        $('reply-textarea').placeholder = 'Écrivez votre réponse…';
        toast('Brouillon prêt', 'success');
    } catch (e) {
        toast(e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/></svg> Générer avec l'IA`;
    }
}

/* Envoyer */
async function sendReply() {
    if (!currentEmail) return;
    const body = $('reply-textarea').value.trim();
    if (!body) { toast('Le message est vide', 'error'); return; }

    const btn = $('btn-send');
    btn.disabled = true;
    btn.textContent = 'Envoi…';

    try {
        const r = await fetch(`/emails/${currentEmail.id}/reply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ body }),
        });
        if (r.status === 401) { window.location.href = '/auth/logout'; return; }
        if (!r.ok) throw new Error(`Erreur ${r.status}`);
        $('reply-textarea').value = '';
        toast('Envoyé', 'success');
    } catch (e) {
        toast(e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg> Envoyer`;
    }
}

/* STT Groq Whisper */
let _recorder = null;
let _chunks = [];
let _recording = false;

async function toggleRecording() {
    if (_recording) {
        stopRecording();
    } else {
        await startRecording();
    }
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        _chunks = [];
        _recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });

        _recorder.ondataavailable = e => { if (e.data.size > 0) _chunks.push(e.data); };
        _recorder.onstop = sendToWhisper;
        _recorder.start();

        _recording = true;
        $('btn-mic').classList.add('recording');
        $('mic-label').textContent = 'Arrêter';
    } catch (e) {
        toast('Accès micro refusé', 'error');
    }
}

function stopRecording() {
    if (_recorder && _recorder.state !== 'inactive') {
        _recorder.stop();
        _recorder.stream.getTracks().forEach(t => t.stop());
    }
    _recording = false;
    $('btn-mic').classList.remove('recording');
    $('mic-label').textContent = 'Transcription…';
    $('btn-mic').disabled = true;
}

async function sendToWhisper() {
    try {
        const blob = new Blob(_chunks, { type: 'audio/webm' });
        const form = new FormData();
        form.append('file', blob, 'audio.webm');

        const r = await fetch('/transcribe', { method: 'POST', body: form });
        if (!r.ok) throw new Error(`Erreur ${r.status}`);

        const data = await r.json();
        const text = data.text?.trim();

        if (text) {
            const ta = $('reply-textarea');
            // Insère après le curseur ou à la fin
            const pos = ta.selectionStart;
            const before = ta.value.slice(0, pos);
            const after = ta.value.slice(pos);
            ta.value = before + text + after;
            ta.selectionStart = ta.selectionEnd = pos + text.length;
            ta.focus();
            toast('Transcription ajoutée', 'success');
        } else {
            toast('Rien capté, réessaie', 'error');
        }
    } catch (e) {
        toast(e.message, 'error');
    } finally {
        $('mic-label').textContent = 'Dicter';
        $('btn-mic').disabled = false;
    }
}

/* TTS Groq Orpheus */
let _audio = null;

async function speakSummary() {
    const text = $('ai-summary').textContent.trim();
    if (!text || text === 'Analyse en cours…') return;

    const btn = $('btn-speak');

    // Si déjà en cours, on arrête
    if (_audio && !_audio.paused) {
        _audio.pause();
        _audio.currentTime = 0;
        btn.classList.remove('speaking');
        return;
    }

    try {
        btn.classList.add('speaking');
        toast('Génération audio…', 'success');

        const r = await fetch('/speak', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, voice: 'autumn' })
        });

        if (!r.ok) throw new Error(`Erreur ${r.status}`);

        const blob = await r.blob();
        const url = URL.createObjectURL(blob);

        if (_audio) { _audio.pause(); URL.revokeObjectURL(_audio.src); }
        _audio = new Audio(url);

        _audio.onended = () => btn.classList.remove('speaking');
        _audio.onerror = () => { toast('Erreur de lecture', 'error'); btn.classList.remove('speaking'); };

        await _audio.play();

    } catch (e) {
        toast(e.message, 'error');
        btn.classList.remove('speaking');
    }
}

/* Init check auth first */
checkAuth();
