#!/usr/bin/env python3
"""
로컬 서버 — .env 파일로 API 키를 관리합니다.
실행: python3 server.py
접속: http://localhost:8765
"""
import json, os, uuid, base64, time, subprocess, tempfile, threading, urllib.request, urllib.parse, urllib.error
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ENV_FILE      = Path(__file__).parent / '.env'
SKILLS_DIR    = Path(__file__).parent / 'claude-youtube-main/skills/claude-youtube'
YT_SKILLS_DIR = Path(__file__).parent / 'youtube-skills-main/skills'
WF_DIR        = Path(__file__).parent / 'comfyui_workflows'

def load_env():
    keys = {
        'YOUTUBE_API_KEY': '',
        'GEMINI_API_KEY': '',
        'GEMINI_MODEL': 'gemini-2.5-flash',
        'TRANSCRIPT_API_KEY': '',
        'XAI_API_KEY': '',
        'COMFYUI_URL': 'http://100.78.58.105:8000',
    }
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                keys[k.strip()] = v.strip()
    return keys

def save_env(data):
    content = (
        f"YOUTUBE_API_KEY={data.get('YOUTUBE_API_KEY', '')}\n"
        f"GEMINI_API_KEY={data.get('GEMINI_API_KEY', '')}\n"
        f"GEMINI_MODEL={data.get('GEMINI_MODEL', 'gemini-2.5-flash')}\n"
        f"TRANSCRIPT_API_KEY={data.get('TRANSCRIPT_API_KEY', '')}\n"
        f"XAI_API_KEY={data.get('XAI_API_KEY', '')}\n"
        f"COMFYUI_URL={data.get('COMFYUI_URL', 'http://100.78.58.105:8000')}\n"
    )
    ENV_FILE.write_text(content, encoding='utf-8')

# ── ComfyUI REST API 클라이언트 ─────────────────────────────────────────────

def _comfyui_base():
    return load_env().get('COMFYUI_URL', 'http://100.78.58.105:8000').rstrip('/')

def _comfyui_req(method, path, data=None, raw=None, ctype='application/json', timeout=30):
    url = _comfyui_base() + path
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(url, data=body, method=method)
    if ctype and body is not None:
        req.add_header('Content-Type', ctype)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def comfyui_upload_image(b64_data):
    """base64 이미지를 ComfyUI에 업로드 → 파일명 반환"""
    img_bytes = base64.b64decode(b64_data.split(',')[-1])
    bnd = uuid.uuid4().hex
    body = (
        f'--{bnd}\r\nContent-Disposition: form-data; name="image"; filename="upload.png"\r\n'
        f'Content-Type: image/png\r\n\r\n'
    ).encode() + img_bytes + f'\r\n--{bnd}--\r\n'.encode()
    res = _comfyui_req('POST', '/upload/image', raw=body,
                       ctype=f'multipart/form-data; boundary={bnd}')
    return res.get('name', 'upload.png')

def comfyui_queue(workflow):
    """워크플로 제출 → prompt_id 반환"""
    cid = uuid.uuid4().hex
    res = _comfyui_req('POST', '/prompt', data={'prompt': workflow, 'client_id': cid})
    return res.get('prompt_id')

def comfyui_get_output(prompt_id):
    """history에서 완료된 출력 파일 정보 반환. 미완료/오류는 (None, state) 반환"""
    hist = _comfyui_req('GET', f'/history/{prompt_id}', timeout=10)
    if prompt_id not in hist:
        return None, 'pending'
    entry = hist[prompt_id]
    status_str = entry.get('status', {}).get('status_str', '')
    if status_str == 'error':
        msgs = entry.get('status', {}).get('messages', [])
        return None, f'error:{msgs}'
    for node_out in entry.get('outputs', {}).values():
        for key in ('gifs', 'videos', 'images'):
            for item in node_out.get(key, []):
                if item.get('filename'):
                    return item, 'done'
    return None, 'pending'

def wan_queue(prompt, mode='t2v', image_b64=None, seed=-1):
    """ComfyUI 워크플로 제출 → prompt_id 반환"""
    import random
    actual_seed = seed if seed >= 0 else random.randint(0, 2147483647)
    wf_file = WF_DIR / ('wan_i2v.json' if (mode == 'i2v' and image_b64) else 'wan_t2v.json')
    wf = json.loads(wf_file.read_text(encoding='utf-8'))
    wf_str = json.dumps(wf)
    wf_str = wf_str.replace('"__PROMPT__"', json.dumps(prompt))
    wf_str = wf_str.replace('-1', str(actual_seed))
    if mode == 'i2v' and image_b64:
        img_name = comfyui_upload_image(image_b64)
        wf_str = wf_str.replace('"__IMAGE_FILENAME__"', json.dumps(img_name))
    return comfyui_queue(json.loads(wf_str))

def wan_get_status(prompt_id):
    """ComfyUI history 폴링 → {'status', 'video_url'?}"""
    try:
        item, state = comfyui_get_output(prompt_id)
    except Exception as e:
        return {'status': 'pending', 'debug': str(e)}
    if state == 'pending':
        return {'status': 'pending'}
    if state.startswith('error:'):
        return {'status': 'error', 'error': state[6:]}
    fn   = urllib.parse.quote(item['filename'])
    ftype = item.get('type', 'output')
    subfolder = item.get('subfolder', '')
    url = f'/api/wan/video?filename={fn}&type={ftype}&subfolder={urllib.parse.quote(subfolder)}'
    return {'status': 'done', 'video_url': url}

# ── claude-youtube-main 스킬 (YouTube Creator AI) ──
def get_skill_content(skill_name):
    parts = []
    main_md = SKILLS_DIR / 'SKILL.md'
    if main_md.exists():
        parts.append(main_md.read_text(encoding='utf-8'))
    sub_md = SKILLS_DIR / 'sub-skills' / f'{skill_name}.md'
    if sub_md.exists():
        parts.append(sub_md.read_text(encoding='utf-8'))
    return '\n\n---\n\n'.join(parts)

def list_skills():
    sub_dir = SKILLS_DIR / 'sub-skills'
    if not sub_dir.exists():
        return []
    return sorted(p.stem for p in sub_dir.glob('*.md'))

# ── youtube-skills-main 스킬 (TranscriptAPI) ──
def get_yt_skill_content(skill_name):
    skill_md = YT_SKILLS_DIR / skill_name / 'SKILL.md'
    if skill_md.exists():
        return skill_md.read_text(encoding='utf-8')
    return ''

def list_yt_skills():
    if not YT_SKILLS_DIR.exists():
        return []
    return sorted(
        p.name for p in YT_SKILLS_DIR.iterdir()
        if p.is_dir() and (p / 'SKILL.md').exists()
    )

def _send_json(handler, status, obj):
    body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', len(body))
    handler.end_headers()
    handler.wfile.write(body)

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/config':
            _send_json(self, 200, load_env())

        elif self.path == '/api/skills':
            _send_json(self, 200, {'skills': list_skills()})

        elif self.path.startswith('/api/skill/'):
            skill_name = self.path[len('/api/skill/'):]
            if not skill_name.replace('-', '').replace('_', '').isalnum():
                self.send_response(400); self.end_headers(); return
            content = get_skill_content(skill_name)
            if not content:
                self.send_response(404); self.end_headers(); return
            _send_json(self, 200, {'content': content})

        elif self.path == '/api/yt-skills':
            _send_json(self, 200, {'skills': list_yt_skills()})

        elif self.path.startswith('/api/yt-skill/'):
            skill_name = self.path[len('/api/yt-skill/'):]
            if not skill_name.replace('-', '').replace('_', '').isalnum():
                self.send_response(400); self.end_headers(); return
            content = get_yt_skill_content(skill_name)
            if not content:
                self.send_response(404); self.end_headers(); return
            _send_json(self, 200, {'content': content})

        elif self.path.startswith('/api/comfyui/status/'):
            prompt_id = self.path[len('/api/comfyui/status/'):]
            try:
                result = wan_get_status(prompt_id)
                _send_json(self, 200, result)
            except Exception as e:
                _send_json(self, 500, {'error': str(e)})

        elif self.path.startswith('/api/wan/video'):
            qs        = urllib.parse.parse_qs(self.path.split('?', 1)[-1])
            filename  = qs.get('filename', [''])[0]
            ftype     = qs.get('type', ['output'])[0]
            subfolder = qs.get('subfolder', [''])[0]
            if not filename:
                _send_json(self, 400, {'error': 'filename 없음'}); return
            comfy_url = (f"{_comfyui_base()}/view"
                         f"?filename={urllib.parse.quote(filename)}"
                         f"&type={ftype}"
                         f"&subfolder={urllib.parse.quote(subfolder)}")
            try:
                req = urllib.request.Request(comfy_url)
                with urllib.request.urlopen(req, timeout=60) as r:
                    video_data = r.read()
                    ctype = r.headers.get('Content-Type', 'video/mp4')
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', len(video_data))
                self.send_header('Content-Disposition',
                                 f'inline; filename="{filename}"')
                self.end_headers()
                self.wfile.write(video_data)
            except Exception as e:
                _send_json(self, 500, {'error': str(e)})

        else:
            super().do_GET()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body_raw = self.rfile.read(length)

        if self.path == '/api/config':
            data = json.loads(body_raw)
            save_env(data)
            _send_json(self, 200, {'ok': True})

        elif self.path == '/api/proxy/transcriptapi':
            data = json.loads(body_raw)
            endpoint = data.get('endpoint', '')
            params   = data.get('params', {})

            allowed = [
                '/api/v2/youtube/transcript',
                '/api/v2/youtube/search',
                '/api/v2/youtube/channel/',
                '/api/v2/youtube/playlist/',
            ]
            if not any(endpoint.startswith(p) for p in allowed):
                _send_json(self, 400, {'error': 'invalid endpoint'}); return

            api_key = load_env().get('TRANSCRIPT_API_KEY', '')
            if not api_key:
                _send_json(self, 400, {'error': 'TRANSCRIPT_API_KEY not set'}); return

            qs  = urllib.parse.urlencode({k: v for k, v in params.items() if v not in ('', None)})
            url = f'https://transcriptapi.com{endpoint}?{qs}'
            req = urllib.request.Request(url, headers={
                'Authorization': f'Bearer {api_key}',
                'User-Agent': 'YouTubeContentTool/1.0',
            })
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    resp_body = resp.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(resp_body))
                self.end_headers()
                self.wfile.write(resp_body)
            except urllib.error.HTTPError as e:
                err_body = e.read() or b'{}'
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(err_body))
                self.end_headers()
                self.wfile.write(err_body)
            except Exception as e:
                _send_json(self, 500, {'error': str(e)})

        elif self.path == '/api/proxy/gemini-image':
            data = json.loads(body_raw)
            api_key = load_env().get('GEMINI_API_KEY', '')
            if not api_key:
                _send_json(self, 400, {'error': 'GEMINI_API_KEY not set'}); return

            prompt = data.get('prompt', '')
            model  = data.get('model', 'imagen-4.0-fast-generate-001')
            req_body = json.dumps({
                'instances': [{'prompt': prompt}],
                'parameters': {'sampleCount': 1},
            }).encode('utf-8')
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:predict?key={api_key}'
            req = urllib.request.Request(
                url,
                data=req_body,
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'YouTubeContentTool/1.0',
                }
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    resp_body = resp.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(resp_body))
                self.end_headers()
                self.wfile.write(resp_body)
            except urllib.error.HTTPError as e:
                err_body = e.read() or b'{}'
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(err_body))
                self.end_headers()
                self.wfile.write(err_body)
            except Exception as e:
                _send_json(self, 500, {'error': str(e)})

        elif self.path == '/api/comfyui/queue':
            data    = json.loads(body_raw)
            mode    = data.get('mode', 't2v')
            prompt  = data.get('prompt', '')
            img_b64 = data.get('image_b64', '')
            try:
                prompt_id = wan_queue(
                    prompt    = prompt,
                    mode      = mode,
                    image_b64 = img_b64 if mode == 'i2v' else None,
                    seed      = data.get('seed', -1),
                )
                _send_json(self, 200, {'prompt_id': prompt_id})
            except Exception as e:
                _send_json(self, 500, {'error': str(e)})

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass  # 로그 출력 끄기

if __name__ == '__main__':
    port = 8765
    os.chdir(Path(__file__).parent)
    server = HTTPServer(('localhost', port), Handler)
    print(f'✅ 서버 실행 중 → http://localhost:{port}')
    print('   종료: Ctrl+C')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n서버 종료')
