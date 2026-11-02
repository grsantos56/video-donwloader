from flask import Flask, render_template, request, Response, jsonify, stream_with_context, send_file
from flask_cors import CORS
import subprocess
import json
import sys
import re
import os
import shutil
import uuid
import glob
import tempfile
import base64
import urllib.request
import urllib.parse


# Try to find FFmpeg in winget packages and add it to PATH dynamically
def setup_ffmpeg():
    winget_packages_dir = r"C:\Users\gabri\AppData\Local\Microsoft\WinGet\Packages"
    if os.path.exists(winget_packages_dir):
        for entry in os.listdir(winget_packages_dir):
            if "FFmpeg" in entry:
                package_path = os.path.join(winget_packages_dir, entry)
                for root, dirs, files in os.walk(package_path):
                    if "ffmpeg.exe" in files:
                        os.environ["PATH"] += os.pathsep + root
                        return True
    return False

setup_ffmpeg()


# Start bgutil PO Token HTTP server in background if installed (Docker/Render)
_bgutil_proc = None
def start_bgutil_server():
    global _bgutil_proc
    bgutil_main = "/opt/bgutil/server/build/main.js"
    if os.path.exists(bgutil_main) and shutil.which("node"):
        try:
            _bgutil_proc = subprocess.Popen(
                ["node", "build/main.js", "--port", "4416"],
                cwd="/opt/bgutil/server",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )
            print("[INFO] Started bgutil PO Token server on port 4416", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] Could not start bgutil server: {e}", file=sys.stderr)

start_bgutil_server()


app = Flask(__name__)
CORS(app)  # Enable Cross-Origin Resource Sharing

# Helper to sanitize filenames
def sanitize_filename(name):
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    return cleaned.strip() or "video"

# Helper to load YouTube cookies (from file or environment variable, raw or base64)
def get_cookie_file():
    if os.path.exists("cookies.txt") and os.path.getsize("cookies.txt") > 0:
        return "cookies.txt"
    cookies_env = os.environ.get("YOUTUBE_COOKIES")
    if cookies_env:
        raw = cookies_env.strip()
        # Check if base64 encoded
        if "youtube.com" not in raw and "Netscape" not in raw:
            try:
                decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
                if "youtube.com" in decoded or "Netscape" in decoded:
                    raw = decoded
            except Exception:
                pass
        content = raw.replace("\\n", "\n").replace("\r\n", "\n")
        lines = []
        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                lines.append(line)
                continue
            # Ensure Netscape cookie format uses tabs if spaces were pasted
            if "\t" not in stripped and len(stripped.split()) >= 7:
                parts = stripped.split(None, 6)
                lines.append("\t".join(parts))
            else:
                lines.append(line)
        cookie_path = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
        with open(cookie_path, "w", encoding="utf-8") as f:
            if not any("Netscape HTTP Cookie File" in l for l in lines[:3]):
                f.write("# Netscape HTTP Cookie File\n")
            f.write("\n".join(lines) + "\n")
        return cookie_path
    return None

def is_youtube_url(url):
    if not url:
        return False
    u = url.lower()
    return "youtube.com/" in u or "youtu.be/" in u

def extract_youtube_id(url):
    patterns = [
        r"(?:v=|\/videos\/|embed\/|youtu\.be\/|\/v\/|\/e\/|watch\?v=|&v=|shorts\/)([0-9A-Za-z_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None

def format_duration_seconds(duration):
    if not duration:
        return "00:00"
    duration = int(duration)
    h = duration // 3600
    m = (duration % 3600) // 60
    s = duration % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# Fallback 1: Use pytubefix with multi-client & automatic BotGuard PO Token generation
def get_youtube_info_pytubefix(url):
    try:
        from pytubefix import YouTube
    except ImportError:
        return None

    clients = ['WEB', 'MWEB', 'TV', 'ANDROID_VR', 'WEB_EMBED', 'IOS']
    ffmpeg_available = shutil.which("ffmpeg") is not None

    for client in clients:
        try:
            yt = YouTube(url, client=client)
            title = yt.title or "Video"
            duration = yt.length
            thumbnail = yt.thumbnail_url
            streams = yt.streams
            if not streams:
                continue

            video_by_height = {}
            audio_options = []

            for s in streams:
                if s.type == "audio":
                    abr_str = getattr(s, "abr", "") or ""
                    abr_Match = re.search(r"(\d+)", abr_str)
                    abr_val = int(abr_Match.group(1)) if abr_Match else 128
                    ext = (s.subtype or "m4a").lower()
                    fsize = getattr(s, "filesize", None) or getattr(s, "filesize_approx", None)
                    fsize_mb = f"{fsize / (1024 * 1024):.1f} MB" if fsize else "Tamanho desconhecido"
                    audio_options.append({
                        'format_id': f"pytube:{client}:{s.itag}",
                        'ext': ext,
                        'abr': abr_val,
                        'filesize': fsize,
                        'label': f"{abr_val} kbps ({ext.upper()}) - {fsize_mb}",
                        'is_combined': True
                    })
                elif s.type == "video":
                    res = getattr(s, "resolution", None)
                    if not res:
                        continue
                    m = re.search(r"(\d+)", res)
                    if not m:
                        continue
                    height = int(m.group(1))
                    if height < 140:
                        continue
                    ext = (s.subtype or "mp4").lower()
                    if ext not in ['mp4', 'webm']:
                        continue
                    is_combined = bool(getattr(s, "is_progressive", False))
                    if not is_combined and not ffmpeg_available:
                        continue

                    existing = video_by_height.get(height)
                    if not existing or (is_combined and not existing['is_combined']):
                        fsize = getattr(s, "filesize", None) or getattr(s, "filesize_approx", None)
                        if not is_combined and fsize and ffmpeg_available:
                            fsize += 3 * 1024 * 1024
                        fsize_mb = f"{fsize / (1024 * 1024):.1f} MB" if fsize else "Tamanho desconhecido"
                        suffix = " (Alta Qualidade)" if not is_combined else ""
                        video_by_height[height] = {
                            'format_id': f"pytube:{client}:{s.itag}",
                            'ext': 'mp4' if (ffmpeg_available and not is_combined) else ext,
                            'resolution': f"{height}p",
                            'height': height,
                            'filesize': fsize,
                            'label': f"{height}p{suffix} ({ext.upper()}) - {fsize_mb}",
                            'is_combined': is_combined
                        }

            if not video_by_height and not audio_options:
                continue

            dedup_video = sorted(video_by_height.values(), key=lambda x: x['height'], reverse=True)
            audio_options.sort(key=lambda x: x['abr'], reverse=True)
            seen_audio = set()
            dedup_audio = []
            for ao in audio_options:
                if ao['label'] not in seen_audio:
                    seen_audio.add(ao['label'])
                    dedup_audio.append(ao)

            grouped_video = {}
            for vo in dedup_video:
                ext_key = vo['ext'].lower()
                grouped_video.setdefault(ext_key, []).append(vo)

            grouped_audio = {}
            for ao in dedup_audio:
                ext_key = ao['ext'].lower()
                grouped_audio.setdefault(ext_key, []).append(ao)

            print(f"[INFO] Successfully extracted YouTube info via pytubefix ({client})", file=sys.stderr)
            return {
                'title': title,
                'duration': format_duration_seconds(duration),
                'thumbnail': thumbnail,
                'video_formats': grouped_video,
                'audio_formats': grouped_audio
            }
        except Exception as e:
            print(f"[WARN] pytubefix ({client}) failed: {e}", file=sys.stderr)
            continue

    return None


# Fallback 2: Use public Piped / Invidious APIs when Render IP is blocked by YouTube
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi-libre.kavin.rocks",
    "https://pipedapi.tokhmi.xyz",
    "https://pipedapi.moomoo.me",
    "https://piped-api.garudalinux.org",
]

INVIDIOUS_INSTANCES = [
    "https://inv.tux.pizza",
    "https://invidious.nerdvpn.de",
    "https://inv.nadeko.net",
    "https://yewtu.be",
]

def get_youtube_info_external_api(url):
    video_id = extract_youtube_id(url)
    if not video_id:
        return None

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    # Try Piped instances
    for base in PIPED_INSTANCES:
        try:
            req = urllib.request.Request(f"{base}/streams/{video_id}", headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status != 200:
                    continue
                data = json.loads(resp.read().decode("utf-8"))

            title = data.get("title", "YouTube Video")
            duration = data.get("duration", 0)
            thumbnail = data.get("thumbnailUrl")

            grouped_video = {}
            grouped_audio = {}

            for vs in data.get("videoStreams", []):
                if vs.get("videoOnly", False):
                    continue
                s_url = vs.get("url")
                if not s_url:
                    continue
                quality = vs.get("quality", "360p")
                m = re.search(r"(\d+)", quality)
                height = int(m.group(1)) if m else 360
                ext = "mp4" if "mp4" in (vs.get("mimeType") or "").lower() else "webm"
                encoded_url = base64.urlsafe_b64encode(s_url.encode("utf-8")).decode("ascii")
                vo = {
                    'format_id': f"direct:{encoded_url}",
                    'ext': ext,
                    'resolution': f"{height}p",
                    'height': height,
                    'filesize': None,
                    'label': f"{height}p ({ext.upper()}) - Direto",
                    'is_combined': True
                }
                grouped_video.setdefault(ext, []).append(vo)

            for aus in data.get("audioStreams", []):
                s_url = aus.get("url")
                if not s_url:
                    continue
                bitrate = aus.get("bitrate", 128000) // 1000
                ext = "m4a" if "mp4" in (aus.get("mimeType") or "").lower() else "webm"
                encoded_url = base64.urlsafe_b64encode(s_url.encode("utf-8")).decode("ascii")
                ao = {
                    'format_id': f"direct:{encoded_url}",
                    'ext': ext,
                    'abr': bitrate,
                    'filesize': None,
                    'label': f"{bitrate} kbps ({ext.upper()}) - Direto",
                    'is_combined': True
                }
                grouped_audio.setdefault(ext, []).append(ao)

            if grouped_video or grouped_audio:
                return {
                    'title': title,
                    'duration': format_duration_seconds(duration),
                    'thumbnail': thumbnail,
                    'video_formats': grouped_video,
                    'audio_formats': grouped_audio
                }
        except Exception as e:
            print(f"[WARN] Piped instance {base} failed: {e}", file=sys.stderr)
            continue

    # Try Invidious instances
    for base in INVIDIOUS_INSTANCES:
        try:
            req = urllib.request.Request(f"{base}/api/v1/videos/{video_id}", headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status != 200:
                    continue
                data = json.loads(resp.read().decode("utf-8"))

            title = data.get("title", "YouTube Video")
            duration = data.get("lengthSeconds", 0)
            thumbs = data.get("videoThumbnails") or []
            thumbnail = thumbs[0].get("url") if thumbs else f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

            grouped_video = {}
            grouped_audio = {}

            for fs in data.get("formatStreams", []):
                s_url = fs.get("url")
                if not s_url:
                    continue
                res = fs.get("resolution", "360p")
                m = re.search(r"(\d+)", res)
                height = int(m.group(1)) if m else 360
                ext = (fs.get("container") or "mp4").lower()
                encoded_url = base64.urlsafe_b64encode(s_url.encode("utf-8")).decode("ascii")
                vo = {
                    'format_id': f"direct:{encoded_url}",
                    'ext': ext,
                    'resolution': f"{height}p",
                    'height': height,
                    'filesize': None,
                    'label': f"{height}p ({ext.upper()}) - Direto",
                    'is_combined': True
                }
                grouped_video.setdefault(ext, []).append(vo)

            for af in data.get("adaptiveFormats", []):
                if "audio" not in (af.get("type") or "").lower():
                    continue
                s_url = af.get("url")
                if not s_url:
                    continue
                bitrate = int(af.get("bitrate", 128000)) // 1000
                ext = (af.get("container") or "m4a").lower()
                encoded_url = base64.urlsafe_b64encode(s_url.encode("utf-8")).decode("ascii")
                ao = {
                    'format_id': f"direct:{encoded_url}",
                    'ext': ext,
                    'abr': bitrate,
                    'filesize': None,
                    'label': f"{bitrate} kbps ({ext.upper()}) - Direto",
                    'is_combined': True
                }
                grouped_audio.setdefault(ext, []).append(ao)

            if grouped_video or grouped_audio:
                return {
                    'title': title,
                    'duration': format_duration_seconds(duration),
                    'thumbnail': thumbnail,
                    'video_formats': grouped_video,
                    'audio_formats': grouped_audio
                }
        except Exception as e:
            print(f"[WARN] Invidious instance {base} failed: {e}", file=sys.stderr)
            continue

    return None


def build_ytdlp_attempts(url, cookie_file):
    base_cmd = [
        sys.executable, "-m", "yt_dlp",
        "--remote-components", "ejs:github",
        "--no-playlist",
        "--socket-timeout", "15",
    ]
    attempts = []
    if cookie_file:
        attempts.append(base_cmd + ["--cookies", cookie_file])
    if is_youtube_url(url):
        # Attempt 1: With bgutil PO Token HTTP provider + web/mweb/tv
        attempts.append(base_cmd + [
            "--extractor-args", "youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416",
            "--extractor-args", "youtube:player_client=web,mweb,tv"
        ])
        # Attempt 2: With tv_embedded, mweb, android_vr
        attempts.append(base_cmd + [
            "--extractor-args", "youtube:player_client=tv_embedded,mweb,android_vr"
        ])
    else:
        attempts.append(base_cmd)
    return attempts


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'}), 200

@app.route('/templates/logo.ico')
@app.route('/logo.ico')
@app.route('/favicon.ico')
def favicon():
    return send_file('templates/logo.ico', mimetype='image/x-icon')

@app.route('/templates/logo.png')
@app.route('/logo.png')
def logo_png():
    return send_file('templates/logo.png', mimetype='image/png')

@app.route('/ads.txt')
def ads_txt():
    return send_file('templates/ads.txt', mimetype='text/plain')


@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({'error': 'URL is required'}), 400
        
    url = data['url'].strip()
    cookie_file = get_cookie_file()
    
    try:
        attempts = build_ytdlp_attempts(url, cookie_file)
        result = None
        last_err = ""

        for attempt_cmd in attempts:
            cmd = attempt_cmd + ["-j", url]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', stdin=subprocess.DEVNULL)
            if result.returncode == 0 and result.stdout.strip():
                break
            last_err = result.stderr.strip()
            print(f"[WARN] yt-dlp attempt failed: {last_err}", file=sys.stderr)

        if not result or result.returncode != 0:
            # Automatic fallback for YouTube URLs
            if is_youtube_url(url):
                pytube_data = get_youtube_info_pytubefix(url)
                if pytube_data:
                    return jsonify(pytube_data)

                ext_api_data = get_youtube_info_external_api(url)
                if ext_api_data:
                    return jsonify(ext_api_data)

            err_msg = last_err
            err_lower = err_msg.lower()
            if "unsupported url" in err_lower:
                err_msg = "URL não suportada ou site não compatível."
            elif "video unavailable" in err_lower:
                err_msg = "Vídeo indisponível ou privado."
            elif "not a bot" in err_lower or "sign in to confirm" in err_lower or "failed to extract any player response" in err_lower or "workaround" in err_lower:
                err_msg = "O YouTube bloqueou temporariamente o IP do servidor em nuvem (Render). Para liberar 100% dos vídeos do YouTube no Render, adicione a variável de ambiente YOUTUBE_COOKIES no painel do Render com os cookies exportados do navegador."
            else:
                err_msg = err_msg.split('\n')[-1] if err_msg else "Erro desconhecido ao obter informações."
            return jsonify({'error': err_msg}), 400
            
        metadata = json.loads(result.stdout)
        
        title = metadata.get('title', 'Video')
        duration = metadata.get('duration')
        thumbnail = metadata.get('thumbnail')
        formats = metadata.get('formats', [])
        
        ffmpeg_available = shutil.which("ffmpeg") is not None
        
        video_options = []
        audio_options = []
        
        # Group video formats by height to find the best format for each resolution
        video_formats_by_height = {}
        
        # Parse formats
        for f in formats:
            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')
            ext = f.get('ext', '')
            
            # Parse Audio formats
            if (vcodec == 'none' or vcodec is None) and (acodec != 'none' and acodec is not None):
                abr = f.get('abr')
                bitrate = f"{int(abr)} kbps" if abr else "Áudio"
                filesize = f.get('filesize') or f.get('filesize_approx')
                filesize_mb = f"{filesize / (1024 * 1024):.1f} MB" if filesize else "Tamanho desconhecido"
                
                audio_options.append({
                    'format_id': f.get('format_id'),
                    'ext': ext,
                    'abr': abr or 0,
                    'filesize': filesize,
                    'label': f"{bitrate} ({ext.upper()}) - {filesize_mb}"
                })
                continue
                
            # Parse Video formats
            if vcodec != 'none' and vcodec is not None:
                height = f.get('height')
                # Skip storyboard or tiny formats
                if not height or height < 140:
                    continue
                
                # We prefer MP4 and WEBM extensions for video
                if ext not in ['mp4', 'webm']:
                    continue
                    
                is_combined = acodec != 'none' and acodec is not None
                
                existing = video_formats_by_height.get(height)
                if not existing:
                    video_formats_by_height[height] = f
                else:
                    exist_acodec = existing.get('acodec', 'none')
                    exist_combined = exist_acodec != 'none' and exist_acodec is not None
                    
                    if is_combined and not exist_combined:
                        video_formats_by_height[height] = f
                    elif is_combined == exist_combined:
                        exist_size = existing.get('filesize') or existing.get('filesize_approx') or 0
                        current_size = f.get('filesize') or f.get('filesize_approx') or 0
                        if current_size > exist_size:
                            video_formats_by_height[height] = f
                            
        # Convert the best video formats per height to video_options
        for height, f in video_formats_by_height.items():
            acodec = f.get('acodec', 'none')
            ext = f.get('ext', '')
            is_combined = acodec != 'none' and acodec is not None
            
            resolution_str = f"{height}p"
            
            filesize = f.get('filesize') or f.get('filesize_approx')
            if not is_combined and filesize and ffmpeg_available:
                filesize += 3 * 1024 * 1024
                
            filesize_mb = f"{filesize / (1024 * 1024):.1f} MB" if filesize else "Tamanho desconhecido"
            
            label_suffix = ""
            if not is_combined:
                if ffmpeg_available:
                    label_suffix = " (Alta Qualidade)"
                else:
                    label_suffix = " (Sem Áudio)"
                    
            video_options.append({
                'format_id': f.get('format_id'),
                'ext': 'mp4' if (ffmpeg_available and not is_combined) else ext,
                'resolution': resolution_str,
                'height': height,
                'filesize': filesize,
                'label': f"{resolution_str}{label_suffix} ({ext.upper()}) - {filesize_mb}",
                'is_combined': is_combined
            })
            
        # Sort video options by height descending
        dedup_video = []
        video_options.sort(key=lambda x: x['height'], reverse=True)
        seen_res = set()
        for vo in video_options:
            res = vo['resolution']
            if res not in seen_res:
                seen_res.add(res)
                dedup_video.append(vo)
                
        # Deduplicate and sort audio options by abr descending
        seen_abr = set()
        dedup_audio = []
        audio_options.sort(key=lambda x: x['abr'], reverse=True)
        for ao in audio_options:
            label = ao['label']
            if label not in seen_abr:
                seen_abr.add(label)
                dedup_audio.append(ao)
                
        duration_str = format_duration_seconds(duration)
                
        # Group video formats by extension
        grouped_video = {}
        for vo in dedup_video:
            ext_key = vo['ext'].lower()
            grouped_video.setdefault(ext_key, []).append(vo)
            
        # Group audio formats by extension
        grouped_audio = {}
        for ao in dedup_audio:
            ext_key = ao['ext'].lower()
            grouped_audio.setdefault(ext_key, []).append(ao)

        return jsonify({
            'title': title,
            'duration': duration_str,
            'thumbnail': thumbnail,
            'video_formats': grouped_video,
            'audio_formats': grouped_audio
        })
        
    except Exception as e:
        return jsonify({'error': f'Falha no servidor: {str(e)}'}), 500


def download_with_pytubefix(url, format_id, task_id, ext, is_combined, ffmpeg_available):
    from pytubefix import YouTube
    clients = ['WEB', 'MWEB', 'TV', 'ANDROID_VR', 'WEB_EMBED', 'IOS']
    preferred_client = None
    target_itag = None

    if format_id.startswith("pytube:"):
        parts = format_id.split(":")
        if len(parts) == 3:
            preferred_client = parts[1]
            target_itag = int(parts[2]) if parts[2].isdigit() else None
    elif format_id.isdigit():
        target_itag = int(format_id)

    if preferred_client and preferred_client in clients:
        clients = [preferred_client] + [c for c in clients if c != preferred_client]

    for client in clients:
        try:
            yt = YouTube(url, client=client)
            stream = yt.streams.get_by_itag(target_itag) if target_itag else None
            if not stream:
                if ext in ['m4a', 'mp3', 'opus', 'aac'] or not is_combined:
                    stream = yt.streams.get_audio_only() if ext in ['m4a', 'mp3', 'opus', 'aac'] else yt.streams.get_highest_resolution()
                else:
                    stream = yt.streams.get_highest_resolution()
            if not stream:
                continue

            if stream.type == "video" and not stream.is_progressive and ffmpeg_available:
                video_tmp = os.path.join("downloads", f"{task_id}_v.{stream.subtype or 'mp4'}")
                audio_stream = yt.streams.get_audio_only()
                audio_tmp = os.path.join("downloads", f"{task_id}_a.{audio_stream.subtype or 'm4a'}")
                out_file = os.path.join("downloads", f"{task_id}.mp4")

                stream.download(output_path="downloads", filename=os.path.basename(video_tmp))
                audio_stream.download(output_path="downloads", filename=os.path.basename(audio_tmp))

                merge_cmd = ["ffmpeg", "-y", "-i", video_tmp, "-i", audio_tmp, "-c:v", "copy", "-c:a", "aac", out_file]
                subprocess.run(merge_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

                for tmp_f in (video_tmp, audio_tmp):
                    try:
                        os.remove(tmp_f)
                    except Exception:
                        pass
                if os.path.exists(out_file):
                    return out_file
            else:
                out_ext = stream.subtype or ext or "mp4"
                out_file = os.path.join("downloads", f"{task_id}.{out_ext}")
                stream.download(output_path="downloads", filename=os.path.basename(out_file))
                if os.path.exists(out_file):
                    return out_file
        except Exception as e:
            print(f"[WARN] pytubefix download ({client}) failed: {e}", file=sys.stderr)
            continue
    return None


@app.route('/api/download')
def download():
    url = request.args.get('url')
    format_id = request.args.get('format_id')
    filename = request.args.get('filename', 'download')
    ext = request.args.get('ext', 'mp4')
    is_combined = request.args.get('is_combined', 'true').lower() == 'true'
    
    if not url or not format_id:
        return "URL e format_id são obrigatórios", 400
        
    ffmpeg_available = shutil.which("ffmpeg") is not None
    os.makedirs('downloads', exist_ok=True)
    task_id = str(uuid.uuid4())

    try:
        file_path = None

        # Case 1: Direct URL from external API fallback
        if format_id.startswith("direct:"):
            encoded_url = format_id.split("direct:", 1)[1]
            direct_url = base64.urlsafe_b64decode(encoded_url.encode("ascii")).decode("utf-8")
            out_file = os.path.join("downloads", f"{task_id}.{ext}")
            req = urllib.request.Request(direct_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(out_file, "wb") as f:
                shutil.copyfileobj(resp, f)
            file_path = out_file

        # Case 2: pytubefix stream format
        elif format_id.startswith("pytube:"):
            file_path = download_with_pytubefix(url, format_id, task_id, ext, is_combined, ffmpeg_available)

        # Case 3: Standard yt-dlp download (with fallback to pytubefix for YouTube)
        else:
            format_selector = format_id
            if not is_combined and ffmpeg_available:
                format_selector = f"{format_id}+bestaudio/best"
            out_template = os.path.join("downloads", f"{task_id}.%(ext)s")
            cookie_file = get_cookie_file()

            for attempt_cmd in build_ytdlp_attempts(url, cookie_file):
                cmd = list(attempt_cmd) + ["-f", format_selector, "-o", out_template]
                if not is_combined and ffmpeg_available:
                    cmd.extend(["--merge-output-format", "mp4"])
                cmd.append(url)
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
                if result.returncode == 0:
                    break

            matching_files = glob.glob(os.path.join("downloads", f"{task_id}.*"))
            if matching_files:
                file_path = matching_files[0]
            elif is_youtube_url(url):
                file_path = download_with_pytubefix(url, format_id, task_id, ext, is_combined, ffmpeg_available)

        if not file_path or not os.path.exists(file_path):
            return "Não foi possível processar o download deste vídeo no momento.", 500
            
        actual_ext = os.path.splitext(file_path)[1].lstrip('.')
        safe_filename = sanitize_filename(filename) + f".{actual_ext}"
        
        # Self-deleting binary stream wrapper
        class FileCleanupWrapper:
            def __init__(self, filepath):
                self.filepath = filepath
                self.file = open(filepath, 'rb')
                
            def read(self, blocksize):
                return self.file.read(blocksize)
                
            def close(self):
                self.file.close()
                try:
                    os.remove(self.filepath)
                except Exception:
                    pass
                    
        wrapper = FileCleanupWrapper(file_path)
        
        response = Response(
            stream_with_context(iter(lambda: wrapper.read(65536), b'')),
            mimetype="application/octet-stream"
        )
        response.headers["Content-Disposition"] = f'attachment; filename="{safe_filename}"'
        response.headers["Content-Length"] = os.path.getsize(file_path)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Length"
        return response
        
    except Exception as e:
        return f"Erro no processamento do download: {str(e)}", 500

if __name__ == '__main__':
    # Ensure necessary folders exist
    os.makedirs('templates', exist_ok=True)
    os.makedirs('downloads', exist_ok=True)
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
