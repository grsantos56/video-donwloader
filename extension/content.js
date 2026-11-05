// Injeta um botão "Baixar (MediaFlow)" diretamente abaixo do vídeo no YouTube
(function () {
  const SITE_URL = 'https://video-donwloader-gr0h.onrender.com';

  function injectMediaFlowButton() {
    if (!window.location.pathname.startsWith('/watch')) return;
    if (document.getElementById('mediaflow-yt-btn')) return;

    const actionsContainer =
      document.querySelector('#top-level-buttons-computed') ||
      document.querySelector('ytd-menu-renderer #top-level-buttons-computed');

    if (!actionsContainer) return;

    const btn = document.createElement('button');
    btn.id = 'mediaflow-yt-btn';
    btn.type = 'button';
    btn.innerHTML = '⬇ Baixar';
    btn.title = 'Baixar vídeo ou áudio com MediaFlow';
    btn.style.cssText = [
      'margin-left: 8px',
      'padding: 0 16px',
      'height: 36px',
      'border-radius: 18px',
      'border: none',
      'background: linear-gradient(90deg, #0284c7, #6366f1)',
      'color: #ffffff',
      'font-family: Roboto, Arial, sans-serif',
      'font-size: 14px',
      'font-weight: 600',
      'cursor: pointer',
      'display: inline-flex',
      'align-items: center',
      'justify-content: center',
      'gap: 6px',
      'box-shadow: 0 2px 8px rgba(2, 132, 199, 0.35)'
    ].join(';');

    btn.addEventListener('click', () => {
      const videoUrl = window.location.href;
      window.open(`${SITE_URL}/?url=${encodeURIComponent(videoUrl)}`, '_blank');
    });

    actionsContainer.appendChild(btn);
  }

  const observer = new MutationObserver(() => {
    injectMediaFlowButton();
  });

  observer.observe(document.body, { childList: true, subtree: true });
  injectMediaFlowButton();
})();
