#!/usr/bin/env python3
"""
로컬 서버 — .env 파일로 API 키를 관리합니다.
실행: python3 server.py
접속: http://localhost:8765
"""
import json, os, uuid, base64, time, urllib.request, urllib.parse, urllib.error
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
        'COMFYUI_URL': 'http://100.78.58.105:42004',
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
        f"COMFYUI_URL={data.get('COMFYUI_URL', 'http://100.78.58.105:42004')}\n"
    )
    ENV_FILE.write_text(content, encoding='utf-8')

# ── Wan2GP (Gradio 5) 클라이언트 ───────────────────────────────────────────
# Wan2GP는 Gradio 5 기반 — ComfyUI 워크플로 불필요
# API: POST /gradio_api/call/{endpoint} → {"event_id": "..."}
#      GET  /gradio_api/call/{endpoint}/{event_id} → SSE (data: [...])

# save_inputs 파라미터 인덱스 (Gradio positional args)
_PARAM_IDX = {
    'prompt':        5,
    'resolution':    8,
    'video_length':  9,
    'seed':         13,
    'steps':        15,
    'guidance':     16,
    'image_start':  39,
    'image_end':    40,
}
_SAVE_INPUTS_DEFAULTS = None  # 최초 호출 시 API에서 로드

def _wan_base():
    return load_env().get('COMFYUI_URL', 'http://100.78.58.105:42004').rstrip('/')

def _wan_call(endpoint, args, timeout=30):
    """POST /gradio_api/call/{endpoint} → event_id"""
    url = f'{_wan_base()}/gradio_api/call/{endpoint.lstrip("/")}'
    body = json.dumps({'data': args}).encode()
    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()).get('event_id', '')

def _wan_read_result(endpoint, event_id, timeout=600):
    """GET SSE stream → 최초 data 라인 파싱"""
    url = f'{_wan_base()}/gradio_api/call/{endpoint.lstrip("/")}/{event_id}'
    req = urllib.request.Request(url)
    deadline = time.time() + timeout
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            if time.time() > deadline:
                raise TimeoutError('Wan2GP 응답 시간 초과')
            line = raw.decode('utf-8', errors='replace').rstrip('\n\r')
            if line.startswith('data: '):
                payload = line[6:].strip()
                if payload not in ('', 'null'):
                    return json.loads(payload)
    return None

def _wan_get_defaults():
    global _SAVE_INPUTS_DEFAULTS
    if _SAVE_INPUTS_DEFAULTS is not None:
        return _SAVE_INPUTS_DEFAULTS
    url = f'{_wan_base()}/gradio_api/info'
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as r:
        info = json.loads(r.read())
    params = info['named_endpoints']['/save_inputs']['parameters']
    _SAVE_INPUTS_DEFAULTS = [p.get('parameter_default') for p in params]
    return _SAVE_INPUTS_DEFAULTS

def wan_upload_image(b64_data):
    """base64 이미지를 Wan2GP에 업로드 → FileData dict"""
    img_bytes = base64.b64decode(b64_data.split(',')[-1])
    bnd = uuid.uuid4().hex
    body = (
        f'--{bnd}\r\nContent-Disposition: form-data; name="files"; filename="upload.png"\r\n'
        f'Content-Type: image/png\r\n\r\n'
    ).encode() + img_bytes + f'\r\n--{bnd}--\r\n'.encode()
    url = f'{_wan_base()}/gradio_api/upload'
    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Content-Type', f'multipart/form-data; boundary={bnd}')
    with urllib.request.urlopen(req, timeout=30) as r:
        paths = json.loads(r.read())  # list of server paths
    path = paths[0] if paths else 'upload.png'
    return {'path': path, 'meta': {'_type': 'gradio.FileData'}}

def wan_queue(prompt, mode='t2v', image_b64=None,
              resolution='832x480', video_length=97, seed=-1):
    """save_inputs → process_prompt_and_add_tasks → event_id 반환"""
    args = list(_wan_get_defaults())

    args[_PARAM_IDX['prompt']]      = prompt
    args[_PARAM_IDX['resolution']]  = resolution
    args[_PARAM_IDX['video_length']] = video_length  # 97 ≈ 4s at 24fps
    args[_PARAM_IDX['seed']]        = seed

    if mode == 'i2v' and image_b64:
        file_data = wan_upload_image(image_b64)
        args[_PARAM_IDX['image_start']] = [file_data]

    # Step 1: save_inputs (저장만, 결과 무시해도 됨)
    eid = _wan_call('save_inputs', args, timeout=30)
    _wan_read_result('save_inputs', eid, timeout=30)

    # Step 2: process_prompt_and_add_tasks → generation event_id
    gen_eid = _wan_call('process_prompt_and_add_tasks', [0, ''], timeout=30)
    return gen_eid

def wan_get_status(event_id):
    """refresh_gallery 폴링 → {'status', 'video_url'?}"""
    try:
        eid = _wan_call('refresh_gallery', [], timeout=10)
        result = _wan_read_result('refresh_gallery', eid, timeout=15)
        if not result:
            return {'status': 'pending'}
        # result[1] = GalleryData (list of file dicts)
        gallery = result[1] if len(result) > 1 else []
        if gallery and isinstance(gallery, list) and gallery[0]:
            item = gallery[0]
            if isinstance(item, dict):
                path = item.get('url') or item.get('name', '')
                if path:
                    video_url = f'/api/wan/video?path={urllib.parse.quote(path)}'
                    return {'status': 'done', 'video_url': video_url}
        return {'status': 'pending'}
    except Exception as e:
        return {'status': 'pending', 'debug': str(e)}

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
            event_id = self.path[len('/api/comfyui/status/'):]
            try:
                result = wan_get_status(event_id)
                _send_json(self, 200, result)
            except Exception as e:
                _send_json(self, 500, {'error': str(e)})

        elif self.path.startswith('/api/wan/video'):
            qs   = urllib.parse.parse_qs(self.path.split('?', 1)[-1])
            path = qs.get('path', [''])[0]
            if not path:
                _send_json(self, 400, {'error': 'path 없음'}); return
            # Wan2GP가 상대 경로를 반환하는 경우 절대 URL 구성
            if path.startswith('/'):
                url = f'{_wan_base()}{path}'
            else:
                url = path
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=60) as r:
                    video_data = r.read()
                    ctype = r.headers.get('Content-Type', 'video/mp4')
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', len(video_data))
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
                event_id = wan_queue(
                    prompt   = prompt,
                    mode     = mode,
                    image_b64 = img_b64 if mode == 'i2v' else None,
                    resolution   = data.get('resolution', '832x480'),
                    video_length = data.get('video_length', 97),
                    seed         = data.get('seed', -1),
                )
                _send_json(self, 200, {'prompt_id': event_id})
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
