'use strict';

const root = document.querySelector('#app');
const notice = document.querySelector('#notice');
const state = { token: '', families: [], children: [], members: [], family: null, child: null, page: 'home', filter: '', offset: 0, editing: null, key: '', settings: null, aiConsent: false };
const names = { feeding: 'Minum', diaper: 'Popok', sleep: 'Tidur', growth: 'Pertumbuhan', note: 'Catatan' };
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const field = (label, control, hint = '') => `<div class="field"><label>${label}${control}</label>${hint ? `<small class="muted">${hint}</small>` : ''}</div>`;
const options = (items, selected) => items.map(([value, label]) => `<option value="${esc(value)}"${value === selected ? ' selected' : ''}>${esc(label)}</option>`).join('');
const select = (name, items, value) => `<select name="${name}">${options(items, value)}</select>`;
const localTime = (date = new Date()) => new Intl.DateTimeFormat('sv-SE', {timeZone: state.family?.timezone || 'Asia/Jakarta', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23'}).format(date).replace(' ', 'T');
let toastTimer;
function toast(message) { notice.textContent = message; clearTimeout(toastTimer); toastTimer = setTimeout(() => { notice.textContent = ''; }, 5000); }
async function api(path, {method = 'GET', body, key} = {}) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (key) headers['Idempotency-Key'] = key;
  const result = await fetch(path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache:'no-store'});
  if (!result.ok) {
    if (result.status === 401 && state.token) { state.token = ''; state.families = []; }
    throw new Error(result.status === 409 ? 'Catatan berubah. Muat ulang sebelum mencoba lagi.' : result.status === 403 ? 'Akses keluarga tidak tersedia.' : result.status === 401 ? 'Sesi berakhir atau data Telegram tidak valid.' : 'Permintaan gagal. Periksa data dan coba lagi.');
  }
  return result.status === 204 ? null : result.json();
}
function familyPath() { return `/api/families/${state.family.id}`; }
function childPath() { return `${familyPath()}/children/${state.child.id}`; }
function errorBox(message) { return `<div class="error" role="alert">${esc(message)} <button class="link" type="button" data-action="retry">Coba lagi</button></div>`; }
async function boot() {
  try {
    const config = await api('/api/config');
    const init = window.Telegram?.WebApp?.initData;
    if (init) { const result = await api('/api/session', {method:'POST', body:{init_data:init}}); state.token = result.token; await loadFamilies(); return; }
    root.innerHTML = `<section class="panel"><p class="eyebrow">Ruang keluarga</p><h1>Buka dari Telegram</h1><p>Gunakan tombol Mini App pada bot untuk masuk dengan akun Telegram.</p>${config.development_auth ? `<hr class="divider"><h2>Mode data sintetis</h2><p class="muted">Hanya untuk pengembangan lokal. ID ini bukan identitas Telegram terverifikasi.</p><form id="dev-login">${field('ID pengguna uji', '<input name="user_id" type="number" min="1" required value="1001">')}<button class="primary">Masuk sebagai pengguna uji</button></form>` : ''}</section>`;
  } catch (error) { root.innerHTML = `<section class="panel">${errorBox(error.message)}</section>`; }
}
async function loadFamilies() {
  state.families = await api('/api/families');
  state.family = state.families.find(x => x.id === state.family?.id) || state.families[0] || null;
  if (!state.family) { onboarding(); return; }
  state.children = await api(`${familyPath()}/children`);
  state.child = state.children.find(x => x.id === state.child?.id) || state.children[0] || null;
  await render();
}
function onboarding() {
  root.innerHTML = `<section class="panel"><p class="eyebrow">Mulai bersama</p><h1>Buat ruang keluarga</h1><p class="muted">Catatan dapat dibagikan dengan anggota yang diundang.</p><form id="family-create">${field('Nama keluarga', '<input name="name" maxlength="100" required>')}${field('Nama panggilan anak', '<input name="nickname" maxlength="100" required>')}${field('Zona waktu IANA', '<input name="timezone" value="Asia/Jakarta" required>')}<button class="primary">Buat keluarga</button></form><hr class="divider"><h2>Punya undangan?</h2><form id="redeem">${field('Kode undangan', '<input name="token" required autocomplete="off">')}<button class="secondary">Gabung keluarga</button></form></section>`;
}
function shell(content) {
  const navigation = [['home','Beranda'],['timeline','Timeline'],['add','Tambah'],['growth','Pertumbuhan'],['settings','Pengaturan']];
  const familyOptions = state.families.map(f => [String(f.id), f.name]);
  const childOptions = state.children.map(c => [String(c.id), c.nickname]);
  root.innerHTML = `<div class="layout"><aside><div class="family-switch"><label for="family">Keluarga</label><select id="family">${options(familyOptions, String(state.family.id))}</select></div>${state.children.length ? `<div class="family-switch"><label for="child">Anak</label><select id="child">${options(childOptions, String(state.child?.id))}</select></div>` : ''}<nav class="side" aria-label="Navigasi utama">${navigation.map(([id,label]) => `<button class="nav" data-page="${id}"${state.page === id ? ' aria-current="page"' : ''}>${label}</button>`).join('')}</nav></aside><div id="content">${content}</div></div><p class="footer-note">Ruang Tumbuh membantu mencatat, bukan layanan darurat atau alat diagnosis.</p>`;
  const nav = root.querySelector('.side'), active = nav.querySelector('[aria-current="page"]');
  if (nav.scrollWidth > nav.clientWidth && active) nav.scrollLeft = active.offsetLeft - nav.offsetLeft + active.offsetWidth - nav.clientWidth;
}
function describe(event) {
  const p = event.payload;
  if (event.kind === 'feeding') return `${({direct:'ASI langsung',expressed:'ASIP',formula:'Formula',unknown:'Jenis tidak diketahui'})[p.type] || p.type}${p.volume_ml ? ` · ${p.volume_ml} ml` : ''}${p.duration_minutes ? ` · ${p.duration_minutes} menit` : ''}${p.side ? ` · ${p.side}` : ''}${p.notes ? ` · ${p.notes}` : ''}`;
  if (event.kind === 'diaper') return `${({pup:'Pup',pipis:'Pipis',both:'Pipis dan pup'})[p.type] || p.type}${p.notes ? ` · ${p.notes}` : ''}`;
  if (event.kind === 'growth') return `${({weight:'Berat',length:'Panjang',height:'Tinggi',head_circumference:'Lingkar kepala'})[p.type] || p.type}: ${p.value} ${p.unit}${p.position ? ` · ${p.position === 'recumbent' ? 'berbaring' : 'berdiri'}` : ''}${p.method ? ` · ${p.method}` : ''}${p.notes ? ` · ${p.notes}` : ''}`;
  if (event.kind === 'sleep') return `${p.ended_at ? `Selesai ${formatDate(p.ended_at)}` : 'Waktu selesai belum dicatat'}${p.notes ? ` · ${p.notes}` : ''}`;
  return p.text || '';
}
function formatDate(value) { return new Intl.DateTimeFormat('id-ID', {timeZone:state.family.timezone, dateStyle:'medium', timeStyle:'short'}).format(new Date(value)); }
function eventList(events, edit = true) {
  if (!events.length) return '<p class="empty">Belum ada catatan untuk pilihan ini. Tambahkan catatan saat informasi tersedia.</p>';
  return `<ul class="list">${events.map(event => `<li class="event"><div><strong>${esc(names[event.kind] || event.kind)}</strong><p>${esc(describe(event))}</p><time>${esc(formatDate(event.occurred_at))} · ${esc(state.family.timezone)}</time></div>${edit ? `<div><button class="link" data-edit="${event.id}">Ubah<span class="sr-only"> ${esc(names[event.kind])}</span></button> <button class="link" data-delete="${event.id}">Hapus<span class="sr-only"> ${esc(names[event.kind])}</span></button></div>` : ''}</li>`).join('')}</ul>`;
}
let currentEvents = [];
async function render() {
  if (!state.family) return onboarding();
  shell('<p class="loading" role="status">Memuat data keluarga…</p>');
  if (!state.child && state.page !== 'settings') { shell('<section class="panel"><h1>Belum ada profil anak</h1><p>Profil anak diperlukan untuk mencatat aktivitas.</p></section>'); return; }
  try {
    if (state.page === 'home') {
      const summary = await api(`${childPath()}/summary`);
      const events = await api(`${childPath()}/events?limit=5`);
      const volume = type => summary.volume_counts[type] ? `${summary.volume_ml[type]} ml` : 'belum tercatat';
      shell(`<section class="panel"><p class="eyebrow">Hari ini · ${esc(summary.date)} · ${esc(summary.timezone)}</p><h1>Halo, keluarga ${esc(state.family.name)}</h1><p class="muted">Ringkasan catatan ${esc(state.child.nickname)} untuk hari ini.</p><div class="metric-grid"><div class="metric"><strong>${summary.counts.feeding}</strong><span>catatan minum</span></div><div class="metric"><strong>${summary.counts.diaper}</strong><span>catatan popok</span></div><div class="metric"><strong>${summary.counts.sleep}</strong><span>catatan tidur</span></div></div><p class="muted">Volume tercatat: ASIP ${volume('expressed')} · formula ${volume('formula')}. ASI langsung tidak dihitung sebagai volume.</p><button class="primary" data-page="add">Tambah catatan</button></section><section class="panel"><div class="heading"><h2>Catatan terbaru</h2><button class="link" data-page="timeline">Lihat timeline</button></div>${eventList(events, false)}</section>`);
    } else if (state.page === 'timeline' || state.page === 'growth') {
      const filter = state.page === 'growth' ? 'growth' : state.filter;
      currentEvents = await api(`${childPath()}/events?limit=20&offset=${state.offset}${filter ? `&kind=${encodeURIComponent(filter)}` : ''}`);
      const heading = state.page === 'growth' ? 'Pertumbuhan' : 'Timeline';
      shell(`<section class="panel"><p class="eyebrow">${esc(state.child.nickname)}</p><h1>${heading}</h1><p class="muted">Diurutkan berdasarkan waktu kejadian · ${esc(state.family.timezone)}</p>${state.page === 'growth' ? '<p class="muted">Perbandingan WHO belum tersedia. Pengukuran ini bukan diagnosis.</p>' : field('Filter jenis', select('filter', [['','Semua'],...Object.entries(names)], state.filter))}${eventList(currentEvents)}<div class="actions"><button class="secondary" data-action="previous" ${state.offset === 0 ? 'disabled' : ''}>Sebelumnya</button><button class="secondary" data-action="next" ${currentEvents.length < 20 ? 'disabled' : ''}>Berikutnya</button></div></section>`);
    } else if (state.page === 'add') {
      renderEditor();
    } else if (state.page === 'settings') {
      [state.settings, state.summarySettings] = await Promise.all([
        api(`${familyPath()}/checkin-preferences`),
        api(`${familyPath()}/summary-preferences`),
      ]);
      state.members = await api(`${familyPath()}/members`);
      state.aiConsent = (await api(`${familyPath()}/ai-consent`)).enabled;
      renderSettings();
    }
  } catch (error) { shell(`<section class="panel">${errorBox(error.message)}</section>`); }
}

function renderEditor(kind = state.editing?.kind || 'feeding') {
  const editing = state.editing;
  const p = editing?.kind === kind ? editing.payload : {};
  const text = (name, value = '', type = 'text', extra = '') => `<input name="${name}" type="${type}" value="${esc(value)}" ${extra}>`;
  let details = '';
  if (kind === 'feeding') details = field('Jenis minum', select('type', [['direct','ASI langsung'],['expressed','ASIP'],['formula','Formula'],['unknown','Tidak diketahui']], p.type || 'expressed')) + field('Volume (ml), jika diketahui', text('volume_ml', p.volume_ml, 'number', 'min="0.01" step="any"')) + field('Durasi (menit), ASI langsung', text('duration_minutes', p.duration_minutes, 'number', 'min="0.01" step="any"')) + field('Sisi, ASI langsung', select('side', [['','Tidak dicatat'],['left','Kiri'],['right','Kanan'],['both','Keduanya'],['unknown','Tidak diketahui']], p.side || ''));
  if (kind === 'diaper') details = field('Jenis popok', select('type', [['pup','Pup'],['pipis','Pipis'],['both','Keduanya']], p.type || 'pup'));
  if (kind === 'sleep') details = field('Selesai, jika diketahui', text('ended_local', p.ended_at ? localTime(new Date(p.ended_at)) : '', 'datetime-local', 'step="1"'));
  if (kind === 'growth') details = field('Pengukuran', select('type', [['weight','Berat (kg)'],['length','Panjang (cm)'],['height','Tinggi (cm)'],['head_circumference','Lingkar kepala (cm)']], p.type || 'weight')) + field('Nilai', text('value', p.value, 'number', 'min="0.01" step="any" required')) + field('Posisi pengukuran (wajib untuk panjang/tinggi)', select('position', [['','Pilih posisi'],['recumbent','Berbaring'],['standing','Berdiri']], p.position || '')) + field('Alat atau metode (opsional)', text('method', p.method, 'text', 'maxlength="200"'));
  if (kind === 'note') details = field('Catatan atau pertanyaan konsultasi', `<textarea name="text" maxlength="2000" required>${esc(p.text || '')}</textarea>`);
  if (kind !== 'note') details += field('Catatan tambahan', `<textarea name="notes" maxlength="2000">${esc(p.notes || '')}</textarea>`);
  state.key ||= crypto.randomUUID();
  shell(`<section class="panel"><p class="eyebrow">${esc(state.child.nickname)} · ${esc(state.family.timezone)}</p><h1>${editing ? 'Ubah catatan' : 'Tambah catatan'}</h1>${editing ? `<p class="muted">Sebelumnya: ${esc(describe(editing))} · ${esc(formatDate(editing.occurred_at))}</p>` : '<p class="muted">Isi hanya informasi yang diketahui.</p>'}<form id="event-form">${field('Jenis aktivitas', `<select name="kind" ${editing ? 'disabled' : ''}>${options(Object.entries(names), kind)}</select>`)}${field(kind === 'sleep' ? 'Mulai tidur' : 'Waktu kejadian', text('occurred_local', editing ? localTime(new Date(editing.occurred_at)) : localTime(), 'datetime-local', 'required step="1"'), `Zona keluarga: ${esc(state.family.timezone)}`)}${details}${kind === 'growth' ? '<p class="muted">Pengukuran disimpan sebagai catatan mentah. Nilai dan hasilnya belum divalidasi terhadap standar WHO.</p>' : ''}<div class="actions"><button class="primary">${editing ? 'Simpan perubahan' : 'Simpan catatan'}</button>${editing ? '<button type="button" class="secondary" data-action="cancel-edit">Batal</button>' : ''}</div></form></section>`);
}
function renderSettings() {
  const saved = state.settings;
  const s = saved.settings || {time:'13:00', timezone:state.family.timezone, quiet_start:null, quiet_end:null, snoozed_until:null, max_daily:1};
  const summarySaved = state.summarySettings;
  const summary = summarySaved.settings || {time:'20:00', timezone:state.family.timezone, quiet_start:null, quiet_end:null, snoozed_until:null, max_daily:1, child_id:state.child?.id || state.children[0]?.id};
  const childOptions = state.children.map(item => [String(item.id), item.nickname]);
  const summaryForm = childOptions.length ? `<form id="summary-settings-form"><label class="check"><input type="checkbox" name="enabled" ${summarySaved.enabled ? 'checked' : ''}> Aktifkan ringkasan untuk saya</label><div class="row">${field('Anak', select('child_id', childOptions, String(summary.child_id || '')))}${field('Waktu kirim', `<input type="time" name="time" required value="${esc(summary.time)}">`)}</div><button class="primary">Simpan ringkasan</button></form>` : '<p class="muted">Tambahkan profil anak untuk mengatur ringkasan harian.</p>';
  const owner = state.family.role === 'owner';
  const members = state.members.map(m => `<li class="event"><div><strong>ID ${esc(m.user_id)}</strong><span class="muted">${m.role === 'owner' ? 'Pemilik' : 'Anggota'}</span></div>${owner ? `<div><button class="link" data-role-user="${m.user_id}" data-role="${m.role === 'owner' ? 'member' : 'owner'}">${m.role === 'owner' ? 'Jadikan anggota' : 'Jadikan pemilik'}</button> <button class="link" data-revoke="${m.user_id}">Cabut akses</button></div>` : ''}</li>`).join('');
  const child = state.child;
  const profile = owner ? `<hr class="divider"><form id="child-form"><h2>Profil anak</h2><p class="muted">Tanggal lahir dan informasi prematur bersifat opsional. Tidak digunakan untuk kesimpulan klinis.</p><input type="hidden" name="child_id" value="${esc(child?.id || '')}">${field('Nama panggilan', `<input name="nickname" maxlength="100" required value="${esc(child?.nickname || '')}">`)}${field('Tanggal lahir', `<input type="date" name="birth_date" value="${esc(child?.birth_date || '')}">`)}${field('Jenis kelamin untuk referensi pertumbuhan', select('sex', [['','Belum diisi'],['female','Perempuan'],['male','Laki-laki']], child?.sex || ''))}${field('Informasi prematur', `<textarea name="premature_notes" maxlength="1000">${esc(child?.premature_notes || '')}</textarea>`)}<div class="actions"><button class="primary">Simpan profil</button><button type="button" class="secondary" data-action="new-child">Tambah anak lain</button></div></form>` : '';
  const exportForm = owner ? `<hr class="divider"><form id="export-form"><h2>Ekspor catatan</h2><p class="muted">CSV mencakup semua anak dalam keluarga. Batas tanggal mengikuti zona ${esc(state.family.timezone)}.</p><div class="row">${field('Dari tanggal', '<input type="date" name="start" required>')}${field('Sampai tanggal', '<input type="date" name="end" required>')}</div><button class="secondary">Unduh CSV</button></form>` : '';
  const deletion = owner ? `<hr class="divider"><h2>Hapus keluarga</h2><p>Profil, catatan, undangan, dan jadwal keluarga ini akan dihapus permanen. Semua anggota kehilangan akses.</p><p class="muted">Pesan yang belum terhubung ke keluarga dapat tersimpan sampai pembersihan retensi 7 hari. Bukti penghapusan minimal disimpan 90 hari. Backup dikelola operator dan tidak terhapus otomatis; kebijakan yang disarankan adalah 30 hari.</p><button class="secondary" type="button" data-action="request-delete-family">Siapkan penghapusan</button><div id="delete-confirm-area"></div>` : '';
  shell(`<section class="panel"><p class="eyebrow">Preferensi pribadi</p><h1>Pengaturan</h1><h2>AI eksternal</h2><p class="muted">Pilihan ini berlaku untuk pesan chatmu di keluarga ini. Jika aktif, isi pesan (termasuk catatan aktivitas atau kesehatan anak), waktu pesan, dan zona waktu keluarga dikirim ke endpoint AI kompatibel yang dikonfigurasi operator. Nama keluarga/anak, tanggal lahir profil aktif bila disebut sebagai tanggal lahir, email, username Telegram dan nomor telepon yang dikenali disamarkan; detail lain mungkin tidak terdeteksi. Penyedia endpoint dapat menyimpan atau mencatat data sesuai kebijakannya; tanyakan kebijakan retensi kepada operator. AI tetap tidak memberi diagnosis atau klaim WHO.</p><form id="ai-consent-form"><label class="check"><input type="checkbox" name="enabled" ${state.aiConsent ? 'checked' : ''}> Izinkan pemrosesan pesan chat oleh penyedia AI</label><button class="secondary">Simpan pilihan AI</button></form><hr class="divider"><h2>Check-in harian</h2><p class="muted">Bot menanyakan catatan yang mungkin terlewat. Setelah satu anggota menjawab, check-in keluarga pada tanggal itu ditutup. Pesan tidak dikirim setelah lewat satu jam dari jadwal.</p><form id="settings-form"><label class="check"><input type="checkbox" name="enabled" ${saved.enabled ? 'checked' : ''}> Aktifkan check-in untuk saya</label><div class="row">${field('Waktu', `<input type="time" name="time" required value="${esc(s.time)}">`)}${field('Zona waktu', `<input name="timezone" required value="${esc(s.timezone)}">`)}</div><div class="row">${field('Jam tenang mulai', `<input type="time" name="quiet_start" value="${esc(s.quiet_start || '')}">`)}${field('Jam tenang berakhir', `<input type="time" name="quiet_end" value="${esc(s.quiet_end || '')}">`)}</div>${field('Batas per hari', `<input name="max_daily" type="number" min="1" max="20" value="${esc(s.max_daily)}" required>`)}${s.snoozed_until ? `<p class="muted">Ditunda sampai ${esc(formatDate(s.snoozed_until))}.</p>` : ''}<div class="actions"><button class="primary">Simpan preferensi</button><button type="button" class="secondary" data-action="snooze">Tunda 1 jam</button><button type="button" class="secondary" data-action="unsnooze">Hapus penundaan</button></div></form><hr class="divider"><h2>Ringkasan harian</h2><p class="muted">Kirim ringkasan catatan satu anak setiap hari. Pesan tidak dikirim setelah lewat satu jam dari jadwal.</p>${summaryForm}${profile}<hr class="divider"><h2>Anggota keluarga</h2><ul class="list">${members}</ul><p class="muted">Undangan berlaku sekali selama 24 jam dan tidak mengaktifkan notifikasi.</p>${owner ? '<button class="secondary" data-action="invite">Buat kode undangan</button><p id="invite-result" aria-live="polite"></p>' : '<p class="muted">Hanya pemilik dapat membuat undangan.</p>'}${exportForm}${deletion}<hr class="divider"><form id="redeem"><h2>Gabung keluarga lain</h2>${field('Kode undangan', '<input name="token" required autocomplete="off">')}<button class="secondary">Gunakan kode</button></form></section>`);
}
function payloadFrom(form, kind) {
  const data = new FormData(form), result = {};
  if (kind === 'feeding' || kind === 'diaper' || kind === 'growth') result.type = data.get('type');
  if (kind === 'feeding') {
    if (data.get('volume_ml')) result.volume_ml = Number(data.get('volume_ml'));
    if (data.get('duration_minutes')) result.duration_minutes = Number(data.get('duration_minutes'));
    if (data.get('side')) result.side = data.get('side');
  }
  if (kind === 'sleep' && data.get('ended_local')) result.ended_local = data.get('ended_local');
  if (kind === 'growth') {
    result.value = Number(data.get('value')); result.unit = result.type === 'weight' ? 'kg' : 'cm';
    const expectedPosition = {length:'recumbent',height:'standing'}[result.type];
    if (expectedPosition && data.get('position') !== expectedPosition) throw new Error('Pilih posisi berbaring untuk panjang atau berdiri untuk tinggi.');
    if (expectedPosition) result.position = expectedPosition;
    if (data.get('method')?.trim()) result.method = data.get('method').trim();
  }
  if (kind === 'note') result.text = data.get('text').trim();
  else if (data.get('notes')?.trim()) result.notes = data.get('notes').trim();
  return result;
}
async function saveSettings(form, snooze = undefined) {
  const data = new FormData(form);
  const settings = {time:data.get('time'), timezone:data.get('timezone').trim(), quiet_start:data.get('quiet_start') || null, quiet_end:data.get('quiet_end') || null, max_daily:Number(data.get('max_daily')), snoozed_until:snooze === undefined ? (state.settings.settings?.snoozed_until || null) : snooze};
  await api(`${familyPath()}/checkin-preferences`, {method:'PUT', body:{enabled:data.has('enabled'), settings}});
  toast('Preferensi tersimpan.'); await render();
}
async function saveSummarySettings(form) {
  const data = new FormData(form), saved = state.summarySettings.settings || {};
  const settings = {time:data.get('time'), timezone:saved.timezone || state.family.timezone, quiet_start:saved.quiet_start ?? null, quiet_end:saved.quiet_end ?? null, max_daily:saved.max_daily || 1, snoozed_until:saved.snoozed_until ?? null, child_id:Number(data.get('child_id'))};
  await api(`${familyPath()}/summary-preferences`, {method:'PUT', body:{enabled:data.has('enabled'), settings}});
  toast('Preferensi ringkasan tersimpan.'); await render();
}
root.addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.target;
  const button = form.querySelector('button[type="submit"], button:not([type])');
  if (button?.disabled) return;
  if (button) button.disabled = true;
  try {
    const data = new FormData(form);
    if (form.id === 'dev-login') { state.token = (await api('/api/dev/session', {method:'POST', body:{user_id:Number(data.get('user_id'))}})).token; await loadFamilies(); }
    if (form.id === 'family-create') { await api('/api/families', {method:'POST', body:{name:data.get('name'),nickname:data.get('nickname'),timezone:data.get('timezone')}}); await loadFamilies(); }
    if (form.id === 'redeem') { await api('/api/invitations/redeem', {method:'POST', body:{token:data.get('token')}}); toast('Anda bergabung dengan keluarga.'); await loadFamilies(); }
    if (form.id === 'settings-form') await saveSettings(form);
    if (form.id === 'summary-settings-form') await saveSummarySettings(form);
    if (form.id === 'ai-consent-form') {
      const result = await api(`${familyPath()}/ai-consent`, {method:'PUT', body:{enabled:data.has('enabled')}});
      state.aiConsent = result.enabled; toast(result.enabled ? 'Pemrosesan AI diaktifkan untuk pesanmu.' : 'Pemrosesan AI dinonaktifkan.'); await render();
    }
    if (form.id === 'export-form') {
      const query = new URLSearchParams({start:data.get('start'), end:data.get('end')});
      const response = await fetch(`${familyPath()}/export.csv?${query}`, {headers:{Authorization:`Bearer ${state.token}`}, cache:'no-store'});
      if (!response.ok) throw new Error('Ekspor gagal. Periksa rentang tanggal dan akses Anda.');
      const url = URL.createObjectURL(await response.blob()); const link = document.createElement('a'); link.href = url; link.download = 'ruang-tumbuh.csv'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    if (form.id === 'delete-family-form') {
      await api(`${familyPath()}/delete`, {method:'POST', body:{token:state.deleteToken, phrase:data.get('phrase')}});
      state.deleteToken = ''; state.family = null; state.child = null; state.page = 'home'; toast('Keluarga dihapus.'); await loadFamilies();
    }
    if (form.id === 'child-form') {
      const id = data.get('child_id');
      await api(`${familyPath()}/children${id ? `/${encodeURIComponent(id)}` : ''}`, {method:id ? 'PUT' : 'POST', body:{nickname:data.get('nickname'), birth_date:data.get('birth_date') || null, sex:data.get('sex') || null, premature_notes:data.get('premature_notes') || null}});
      toast('Profil anak tersimpan.'); await loadFamilies();
    }
    if (form.id === 'event-form') {
      const kind = state.editing?.kind || data.get('kind');
      const payload = payloadFrom(form, kind), occurred_local = data.get('occurred_local');
      if (state.editing?.kind === 'sleep' && payload.ended_local && state.editing.payload.ended_at && payload.ended_local === localTime(new Date(state.editing.payload.ended_at))) { payload.ended_at = state.editing.payload.ended_at; delete payload.ended_local; }
      if (state.editing) await api(`${familyPath()}/events/${state.editing.id}/local`, {method:'PUT', body:{kind, payload, occurred_local, occurred_original:state.editing.occurred_at, version:state.editing.version}});
      else await api(`${childPath()}/events-local`, {method:'POST', key:state.key, body:{kind, payload, occurred_local}});
      state.key = ''; state.editing = null; state.page = 'timeline'; state.offset = 0; toast('Catatan tersimpan.'); await render();
    }
  } catch (error) { toast(error.message); }
  finally { if (button) button.disabled = false; }
});
root.addEventListener('change', async event => {
  try {
    if (event.target.id === 'family') { state.family = state.families.find(f => f.id === Number(event.target.value)); state.child = null; state.offset = 0; state.page = 'home'; await loadFamilies(); }
    if (event.target.id === 'child') { state.child = state.children.find(c => c.id === Number(event.target.value)); state.offset = 0; await render(); }
    if (event.target.name === 'filter') { state.filter = event.target.value; state.offset = 0; await render(); }
    if (event.target.name === 'kind') renderEditor(event.target.value);
  } catch (error) { toast(error.message); }
});
root.addEventListener('click', async event => {
  const target = event.target.closest('button'); if (!target) return;
  try {
    if (target.dataset.page) { state.page = target.dataset.page; state.offset = 0; state.editing = null; state.key = ''; await render(); }
    if (target.dataset.edit) { state.editing = currentEvents.find(item => item.id === Number(target.dataset.edit)); state.page = 'add'; state.key = ''; await render(); }
    if (target.dataset.delete) { const item = currentEvents.find(entry => entry.id === Number(target.dataset.delete)); if (item && confirm(`Hapus catatan ${names[item.kind]} pada ${formatDate(item.occurred_at)}? Catatan disembunyikan, audit dan backup dapat tetap tersimpan.`)) { await api(`${familyPath()}/events/${item.id}/delete`, {method:'POST', body:{version:item.version, confirmed:true}}); toast('Catatan dihapus.'); await render(); } }
    if (target.dataset.action === 'cancel-edit') { state.editing = null; state.page = 'timeline'; await render(); }
    if (target.dataset.action === 'retry') { if (state.token) await loadFamilies(); else await boot(); }
    if (target.dataset.action === 'next') { state.offset += 20; await render(); }
    if (target.dataset.action === 'previous') { state.offset = Math.max(0, state.offset - 20); await render(); }
    if (target.dataset.action === 'invite') { target.disabled = true; const result = await api(`${familyPath()}/invitations`, {method:'POST'}); document.querySelector('#invite-result').textContent = `Kode: ${result.token} · berlaku 24 jam, sekali pakai.`; }
    if (target.dataset.action === 'request-delete-family') { target.disabled = true; const result = await api(`${familyPath()}/deletion-request`, {method:'POST'}); state.deleteToken = result.token; document.querySelector('#delete-confirm-area').innerHTML = `<form id="delete-family-form"><p>Konfirmasi berlaku selama 10 menit.</p>${field('Ketik HAPUS KELUARGA untuk melanjutkan', '<input name="phrase" autocomplete="off" required>')}<button class="secondary">Hapus keluarga permanen</button></form>`; }
    if (target.dataset.action === 'new-child') { const form = document.querySelector('#child-form'); form.reset(); form.elements.child_id.value = ''; form.elements.nickname.value = ''; form.elements.birth_date.value = ''; form.elements.sex.value = ''; form.elements.premature_notes.value = ''; form.elements.nickname.focus(); }
    if (target.dataset.revoke && confirm(`Cabut akses anggota ${target.dataset.revoke}?`)) { await api(`${familyPath()}/members/${target.dataset.revoke}`, {method:'DELETE'}); toast('Akses dicabut.'); await loadFamilies(); }
    if (target.dataset.roleUser && confirm(`Ubah peran anggota ${target.dataset.roleUser}?`)) { await api(`${familyPath()}/members/${target.dataset.roleUser}/role`, {method:'PUT',body:{role:target.dataset.role}}); toast('Peran diperbarui.'); await loadFamilies(); }
    if (target.dataset.action === 'snooze') await saveSettings(document.querySelector('#settings-form'), new Date(Date.now() + 3600000).toISOString());
    if (target.dataset.action === 'unsnooze') await saveSettings(document.querySelector('#settings-form'), null);
  } catch (error) { toast(error.message); }
  finally { target.disabled = false; }
});
boot();
