const RENDER_BACKEND_URL = 'https://video-donwloader-gr0h.onrender.com';
const LOCAL_BACKEND_URL = 'http://localhost:5000';
let activeBackendUrl = RENDER_BACKEND_URL;

const urlInput = document.getElementById('url-input');
const analyzeBtn = document.getElementById('analyze-btn');
const errorBox = document.getElementById('error-box');
const loadingBox = document.getElementById('loading-box');
const resultBox = document.getElementById('result-box');

const videoThumb = document.getElementById('video-thumb');
const videoDuration = document.getElementById('video-duration');
const videoTitle = document.getElementById('video-title');

const tabVideo = document.getElementById('tab-video');
const tabAudio = document.getElementById('tab-audio');
const formatsList = document.getElementById('formats-list');
const downloadBtn = document.getElementById('download-btn');
const dlFeedback = document.getElementById('dl-feedback');

let videoData = null;
let currentTabType = 'video';
let selectedFormat = null;

const SUPPORTED_HOSTS = [
  'youtube.com',
  'youtu.be',
  'tiktok.com',
  'instagram.com',
  'twitter.com',
  'x.com',
  'facebook.com',
  'fb.watch',
  'twitch.tv',
  'vimeo.com',
  'reddit.com'
];

function isSupportedVideoUrl(url) {
  if (!url || !url.startsWith('http')) return false;
  try {
    const parsed = new URL(url);
    return SUPPORTED_HOSTS.some(h => parsed.hostname.includes(h));
  } catch {
    return false;
  }
}

async function detectBackend() {
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 600);
    const res = await fetch(`${LOCAL_BACKEND_URL}/api/health`, { signal: ctrl.signal });
    clearTimeout(timer);
    if (res.ok) {
      activeBackendUrl = LOCAL_BACKEND_URL;
      return;
    }
  } catch {}
  activeBackendUrl = RENDER_BACKEND_URL;
  fetch(`${RENDER_BACKEND_URL}/api/health`).catch(() => {});
}

async function analyzeUrl(url) {
  if (!url) return;
  errorBox.style.display = 'none';
  resultBox.style.display = 'none';
  loadingBox.style.display = 'block';
  analyzeBtn.disabled = true;

  try {
    const response = await fetch(`${activeBackendUrl}/api/info`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || 'Erro ao analisar vídeo.');
    }
    videoData = data;
    renderResult(data);
  } catch (err) {
    errorBox.textContent = err.message || 'Não foi possível conectar ao servidor.';
    errorBox.style.display = 'block';
  } finally {
    loadingBox.style.display = 'none';
    analyzeBtn.disabled = false;
  }
}

function renderResult(data) {
  videoThumb.src = data.thumbnail || '';
  videoDuration.textContent = data.duration || '00:00';
  videoTitle.textContent = data.title || 'Vídeo';
  resultBox.style.display = 'block';
  switchTab('video');
}

function switchTab(type) {
  currentTabType = type;
  tabVideo.classList.toggle('active', type === 'video');
  tabAudio.classList.toggle('active', type === 'audio');

  formatsList.innerHTML = '';
  selectedFormat = null;

  const groups = type === 'video' ? (videoData.video_formats || {}) : (videoData.audio_formats || {});
  const allFormats = [];
  Object.keys(groups).forEach(ext => {
    (groups[ext] || []).forEach(fmt => allFormats.push(fmt));
  });

  if (allFormats.length === 0) {
    formatsList.innerHTML = '<div style="text-align:center;color:#71717a;font-size:12px;padding:12px;">Nenhum formato disponível.</div>';
    return;
  }

  allFormats.forEach((fmt, idx) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'format-item' + (idx === 0 ? ' selected' : '');
    const parts = (fmt.label || '').split(' - ');
    btn.innerHTML = `
      <span class="format-name">${parts[0] || fmt.ext.toUpperCase()}</span>
      <span class="format-size">${parts[1] || ''}</span>
    `;
    btn.addEventListener('click', () => {
      document.querySelectorAll('.format-item').forEach(el => el.classList.remove('selected'));
      btn.classList.add('selected');
      selectedFormat = fmt;
    });
    formatsList.appendChild(btn);
    if (idx === 0) selectedFormat = fmt;
  });
}

tabVideo.addEventListener('click', () => videoData && switchTab('video'));
tabAudio.addEventListener('click', () => videoData && switchTab('audio'));

analyzeBtn.addEventListener('click', () => {
  analyzeUrl(urlInput.value.trim());
});

urlInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    analyzeUrl(urlInput.value.trim());
  }
});

downloadBtn.addEventListener('click', () => {
  if (!videoData || !selectedFormat) return;
  const url = encodeURIComponent(urlInput.value.trim());
  const filename = encodeURIComponent(videoData.title || 'video');
  const formatId = encodeURIComponent(selectedFormat.format_id);
  const ext = encodeURIComponent(selectedFormat.ext || 'mp4');
  const isCombined = selectedFormat.is_combined !== undefined ? selectedFormat.is_combined : true;

  const downloadUrl = `${activeBackendUrl}/api/download?url=${url}&format_id=${formatId}&filename=${filename}&ext=${ext}&is_combined=${isCombined}`;

  dlFeedback.style.display = 'block';
  downloadBtn.disabled = true;

  if (chrome && chrome.downloads && chrome.downloads.download) {
    chrome.downloads.download({ url: downloadUrl }, () => {
      setTimeout(() => {
        dlFeedback.style.display = 'none';
        downloadBtn.disabled = false;
      }, 4000);
    });
  } else {
    window.open(downloadUrl, '_blank');
    setTimeout(() => {
      dlFeedback.style.display = 'none';
      downloadBtn.disabled = false;
    }, 4000);
  }
});

// Ao abrir o popup, detecta automaticamente a URL da aba atual
document.addEventListener('DOMContentLoaded', async () => {
  await detectBackend();
  if (chrome && chrome.tabs && chrome.tabs.query) {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const currentTab = tabs && tabs[0];
      if (currentTab && currentTab.url) {
        if (isSupportedVideoUrl(currentTab.url)) {
          urlInput.value = currentTab.url;
          analyzeUrl(currentTab.url);
        }
      }
    });
  }
});
