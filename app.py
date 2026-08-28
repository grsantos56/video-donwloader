from flask import Flask, render_template, request, Response, jsonify, stream_with_context
from flask_cors import CORS
import subprocess
import json
import sys
import re
import os
import shutil
import uuid
import glob


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


app = Flask(__name__)
CORS(app)  # Enable Cross-Origin Resource Sharing

# Helper to sanitize filenames
def sanitize_filename(name):
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    return cleaned.strip()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({'error': 'URL is required'}), 400
        
    url = data['url']
    
    # Subprocess command to dump metadata JSON
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        "--no-playlist",
        "--socket-timeout", "15",
        "-j",
        url
    ]
    
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', stdin=subprocess.DEVNULL)
        if result.returncode != 0:
            # Try to capture clean error message from stderr
            err_msg = result.stderr.strip()
            # Clean up the error to make it user friendly
            if "Unsupported URL" in err_msg:
                err_msg = "URL não suportada ou site não compatível."
            elif "Video unavailable" in err_msg:
                err_msg = "Vídeo indisponível ou privado."
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
                
                # If we don't have ffmpeg, we prefer combined formats, or show video-only with warning
                existing = video_formats_by_height.get(height)
                if not existing:
                    video_formats_by_height[height] = f
                else:
                    # Prefer combined format over video-only for same height
                    exist_acodec = existing.get('acodec', 'none')
                    exist_combined = exist_acodec != 'none' and exist_acodec is not None
                    
                    if is_combined and not exist_combined:
                        video_formats_by_height[height] = f
                    elif is_combined == exist_combined:
                        # Compare filesizes to keep the higher bitrate one
                        exist_size = existing.get('filesize') or existing.get('filesize_approx') or 0
                        current_size = f.get('filesize') or f.get('filesize_approx') or 0
                        if current_size > exist_size:
                            video_formats_by_height[height] = f
                            
        # Convert the best video formats per height to video_options
        for height, f in video_formats_by_height.items():
            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')
            ext = f.get('ext', '')
            is_combined = acodec != 'none' and acodec is not None
            
            res = f.get('resolution') or f"{height}p"
            resolution_str = f"{height}p"
            
            filesize = f.get('filesize') or f.get('filesize_approx')
            # If it's video-only and we have ffmpeg, estimate size by adding a generic audio size (~3MB)
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
                'ext': 'mp4' if (ffmpeg_available and not is_combined) else ext, # Force mp4 output for merged formats
                'resolution': resolution_str,
                'height': height,
                'filesize': filesize,
                'label': f"{resolution_str}{label_suffix} ({ext.upper()}) - {filesize_mb}",
                'is_combined': is_combined
            })
            
        # Sort video options by height descending
        dedup_video = []
        video_options.sort(key=lambda x: x['height'], reverse=True)
        # Filters duplicates (should already be deduplicated, but keeping to avoid bugs)
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
                
        # Format duration to MM:SS or HH:MM:SS
        duration_str = "00:00"
        if duration:
            h = duration // 3600
            m = (duration % 3600) // 60
            s = duration % 60
            if h > 0:
                duration_str = f"{h:02d}:{m:02d}:{s:02d}"
            else:
                duration_str = f"{m:02d}:{s:02d}"
                
        return jsonify({
            'title': title,
            'duration': duration_str,
            'thumbnail': thumbnail,
            'video_formats': dedup_video,
            'audio_formats': dedup_audio
        })
        
    except Exception as e:
        return jsonify({'error': f'Falha no servidor: {str(e)}'}), 500

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
    
    # If it's a video-only format and ffmpeg is available, we merge it with the best audio
    format_selector = format_id
    if not is_combined and ffmpeg_available:
        format_selector = f"{format_id}+bestaudio/best"
        
    os.makedirs('downloads', exist_ok=True)
    task_id = str(uuid.uuid4())
    out_template = os.path.join("downloads", f"{task_id}.%(ext)s")
    
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        "--no-playlist",
        "--socket-timeout", "15",
        "-f", format_selector,
        "-o", out_template
    ]
    
    # Force MP4 container if merging video and audio
    if not is_combined and ffmpeg_available:
        cmd.extend(["--merge-output-format", "mp4"])
        
    cmd.append(url)
    
    try:
        # Download locally on server
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
        if result.returncode != 0:
            return f"Erro no download do yt-dlp: {result.stderr}", 500
            
        # Find the downloaded file (dynamic extension match)
        matching_files = glob.glob(os.path.join("downloads", f"{task_id}.*"))
        if not matching_files:
            return "Arquivo baixado não foi encontrado no servidor", 500
            
        file_path = matching_files[0]
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
        return response
        
    except Exception as e:
        return f"Erro no processamento do download: {str(e)}", 500

if __name__ == '__main__':
    # Ensure templates folder exists
    os.makedirs('templates', exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)
