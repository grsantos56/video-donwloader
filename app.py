from flask import Flask, render_template, request, Response, jsonify, stream_with_context
from flask_cors import CORS
import subprocess
import json
import sys
import re
import os

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
        
        video_options = []
        audio_options = []
        
        # Parse formats
        for f in formats:
            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')
            ext = f.get('ext', '')
            
            # Check if it has both audio and video (Combined)
            if vcodec != 'none' and vcodec is not None and acodec != 'none' and acodec is not None:
                height = f.get('height')
                res = f.get('resolution') or (f"{height}p" if height else None) or "Video"
                # Avoid listing storyboard format or tiny low-res files that look like images
                if height and height < 140:
                    continue
                filesize = f.get('filesize') or f.get('filesize_approx')
                filesize_mb = f"{filesize / (1024 * 1024):.1f} MB" if filesize else "Tamanho desconhecido"
                
                video_options.append({
                    'format_id': f.get('format_id'),
                    'ext': ext,
                    'resolution': res,
                    'height': height or 0,
                    'filesize': filesize,
                    'label': f"{res} ({ext.upper()}) - {filesize_mb}"
                })
            # Check if it is audio only
            elif (vcodec == 'none' or vcodec is None) and (acodec != 'none' and acodec is not None):
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
                
        # If no combined format was found, fall back to video-only formats
        if not video_options:
            for f in formats:
                vcodec = f.get('vcodec', 'none')
                acodec = f.get('acodec', 'none')
                ext = f.get('ext', '')
                if (vcodec != 'none' and vcodec is not None) and (acodec == 'none' or acodec is None):
                    height = f.get('height')
                    res = f.get('resolution') or (f"{height}p" if height else None) or "Video"
                    filesize = f.get('filesize') or f.get('filesize_approx')
                    filesize_mb = f"{filesize / (1024 * 1024):.1f} MB" if filesize else "Tamanho desconhecido"
                    
                    video_options.append({
                        'format_id': f.get('format_id'),
                        'ext': ext,
                        'resolution': res,
                        'height': height or 0,
                        'filesize': filesize,
                        'label': f"{res} (Sem Áudio) ({ext.upper()}) - {filesize_mb}"
                    })
                    
        # Deduplicate and sort video options by resolution (height) descending
        seen_res = set()
        dedup_video = []
        # Sort video options first by height descending
        video_options.sort(key=lambda x: x['height'], reverse=True)
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
    
    if not url or not format_id:
        return "URL e format_id são obrigatórios", 400
        
    safe_filename = sanitize_filename(filename) + f".{ext}"
    
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        "--no-playlist",
        "--socket-timeout", "15",
        "-f", format_id,
        "-o", "-",
        url
    ]
    
    def generate():
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        try:
            while True:
                chunk = proc.stdout.read(65536) # 64KB chunks
                if not chunk:
                    break
                yield chunk
        except Exception as e:
            pass
        finally:
            proc.terminate()
            proc.wait()
            
    response = Response(stream_with_context(generate()), mimetype="application/octet-stream")
    # Content-Disposition header triggers download on frontend
    response.headers["Content-Disposition"] = f'attachment; filename="{safe_filename}"'
    return response

if __name__ == '__main__':
    # Ensure templates folder exists
    os.makedirs('templates', exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)
