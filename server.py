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
        'COMFYUI_URL': 'http://100.78.58.105:8004',
        'COMFY_API_KEY': '',
        'POLLINATIONS_TOKEN': '',
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
        f"COMFYUI_URL={data.get('COMFYUI_URL', 'http://100.78.58.105:8004')}\n"
        f"COMFY_API_KEY={data.get('COMFY_API_KEY', '')}\n"
        f"POLLINATIONS_TOKEN={data.get('POLLINATIONS_TOKEN', '')}\n"
    )
    ENV_FILE.write_text(content, encoding='utf-8')

# ── ComfyUI REST API 클라이언트 ─────────────────────────────────────────────

def _comfyui_base():
    return load_env().get('COMFYUI_URL', 'http://100.78.58.105:8004').rstrip('/')

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

def comfyui_queue(workflow, extra_data=None):
    """워크플로 제출 → prompt_id 반환"""
    cid = uuid.uuid4().hex
    body = {'prompt': workflow, 'client_id': cid}
    if extra_data:
        body['extra_data'] = extra_data
    res = _comfyui_req('POST', '/prompt', data=body)
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

WAN_GEN_SCRIPT = r'C:\Users\sharkey\wan_gen.py'
WAN_GEN_PYTHON = r'C:\pinokio\api\wan.git\app\env\Scripts\python.exe'

def wan_queue_ssh(prompt, mode='t2v', image_b64=None):
    """SSH로 데스크탑에서 wan_gen.py 실행 → job_id(타임스탬프) 반환"""
    SSH_OPTS = ['-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=10']
    cmd = [WAN_GEN_PYTHON, WAN_GEN_SCRIPT, prompt]
    ssh_cmd = ['ssh'] + SSH_OPTS + ['sharkey@100.78.58.105',
                                     f'"{WAN_GEN_PYTHON}" "{WAN_GEN_SCRIPT}" "{prompt}"']
    # 백그라운드로 실행 (결과는 SSH 파일 감시로 확인)
    start_ts = int(time.time())
    t = threading.Thread(
        target=lambda: subprocess.run(ssh_cmd, capture_output=True, timeout=960),
        daemon=True
    )
    t.start()
    return str(start_ts)

def wan_queue(prompt, mode='t2v', image_b64=None, seed=-1):
    """ComfyUI 워크플로 제출 → prompt_id 반환"""
    import random
    actual_seed = seed if seed >= 0 else random.randint(0, 2147483647)
    api_key = load_env().get('COMFY_API_KEY', '')

    wf_file = WF_DIR / ('wan_i2v.json' if (mode == 'i2v' and image_b64) else 'wan_t2v.json')
    wf = json.loads(wf_file.read_text(encoding='utf-8'))

    wf_str = json.dumps(wf)
    wf_str = wf_str.replace('"__PROMPT__"', json.dumps(prompt))
    wf_str = wf_str.replace('-1', str(actual_seed))
    if mode == 'i2v' and image_b64:
        img_name = comfyui_upload_image(image_b64)
        wf_str = wf_str.replace('"__IMAGE_FILENAME__"', json.dumps(img_name))

    # API 키는 extra_data로 전달 (hidden inputs는 extra_data에서 읽힘)
    extra_data = {'api_key_comfy_org': api_key} if api_key else None
    return comfyui_queue(json.loads(wf_str), extra_data=extra_data)

WAN_OUT_DIR  = r'C:\pinokio\api\wan.git\app\outputs'
SSH_OPTS_LIST = ['-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=10']

def wan_get_status(job_id):
    """SSH로 출력 디렉토리 감시 → {'status', 'video_url'?}"""
    try:
        since_ts = int(job_id)
    except ValueError:
        return {'status': 'error', 'error': '잘못된 job_id'}
    try:
        dt = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(since_ts))
        ps = (f"powershell -Command \""
              f"Get-ChildItem '{WAN_OUT_DIR}' -Filter *.mp4 "
              f"| Where-Object {{ $_.LastWriteTime -gt '{dt}' }} "
              f"| Sort-Object LastWriteTime -Descending "
              f"| Select-Object -First 1 -ExpandProperty FullName\"")
        r = subprocess.run(
            ['ssh'] + SSH_OPTS_LIST + ['sharkey@100.78.58.105', ps],
            capture_output=True, text=True, timeout=15
        )
        path = r.stdout.strip()
        if not path:
            return {'status': 'pending'}
        # SCP로 노트북에 다운로드
        local = tempfile.mktemp(suffix='.mp4', dir='/tmp')
        remote_scp = path.replace('\\', '/').replace('C:/', '/c/')
        subprocess.run(
            ['scp'] + SSH_OPTS_LIST + [f'sharkey@100.78.58.105:{remote_scp}', local],
            check=True, timeout=120
        )
        video_url = f'/api/wan/video?local={urllib.parse.quote(local)}'
        return {'status': 'done', 'video_url': video_url}
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
            prompt_id = self.path[len('/api/comfyui/status/'):]
            try:
                result = wan_get_status(prompt_id)
                _send_json(self, 200, result)
            except Exception as e:
                _send_json(self, 500, {'error': str(e)})

        elif self.path.startswith('/api/wan/video'):
            qs    = urllib.parse.parse_qs(self.path.split('?', 1)[-1])
            local = qs.get('local', [''])[0]
            if not local or not Path(local).exists():
                _send_json(self, 404, {'error': '영상 파일 없음'}); return
            try:
                video_data = Path(local).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp4')
                self.send_header('Content-Length', len(video_data))
                self.send_header('Content-Disposition',
                                 f'inline; filename="{Path(local).name}"')
                self.end_headers()
                self.wfile.write(video_data)
            except Exception as e:
                _send_json(self, 500, {'error': str(e)})

        elif self.path == '/api/sdwebui/status':
            try:
                with urllib.request.urlopen('http://localhost:7860/sdapi/v1/progress', timeout=3) as r:
                    _send_json(self, 200, {'online': True})
            except Exception:
                _send_json(self, 200, {'online': False})

        else:
            super().do_GET()

    def end_headers(self):
        # HTML/JS/CSS 파일은 항상 최신 버전 제공
        if hasattr(self, 'path') and any(self.path.endswith(ext) for ext in ('.html', '.js', '.css', '/')):
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        super().end_headers()

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

        elif self.path == '/api/proxy/pollinations':
            import base64
            data   = json.loads(body_raw)
            prompt = data.get('prompt', '')
            width  = int(data.get('width',  1024))
            height = int(data.get('height', 1024))
            model  = data.get('model', 'flux')
            seed   = data.get('seed', '')
            if not prompt:
                _send_json(self, 400, {'error': 'prompt required'}); return
            token = load_env().get('POLLINATIONS_TOKEN', '')
            if not token:
                _send_json(self, 401, {'error': 'Pollinations API 키가 필요합니다. 설정 패널에서 enter.pollinations.ai에서 발급받은 키를 입력하세요.'}); return
            # gen.pollinations.ai — 신규 API (Authorization Bearer 방식)
            qs_parts = [f'model={model}', f'width={width}', f'height={height}']
            if seed: qs_parts.append(f'seed={seed}')
            url = f'https://gen.pollinations.ai/image/{urllib.parse.quote(prompt)}?{"&".join(qs_parts)}'
            hdrs = {
                'User-Agent': 'YouTubeContentTool/1.0',
                'Accept': 'image/*,*/*',
            }
            if token:
                hdrs['Authorization'] = f'Bearer {token}'
            req = urllib.request.Request(url, headers=hdrs)
            last_err = None
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    img_bytes = resp.read()
                    ct = resp.headers.get('Content-Type', 'image/jpeg')
                b64 = base64.b64encode(img_bytes).decode()
                _send_json(self, 200, {'b64': b64, 'mimeType': ct})
                last_err = None
            except urllib.error.HTTPError as e:
                err_body = e.read() or b'{}'
                try:
                    msg = json.loads(err_body).get('error', {})
                    if isinstance(msg, dict): msg = msg.get('message', f'HTTP {e.code}')
                except Exception:
                    msg = f'HTTP {e.code}'
                last_err = (e.code, str(msg))
            except Exception as e:
                last_err = (500, str(e))
            if last_err:
                code, msg = last_err
                _send_json(self, code, {'error': f'Pollinations: {msg}'})

        elif self.path == '/api/comfyui/queue':
            data    = json.loads(body_raw)
            mode    = data.get('mode', 't2v')
            prompt  = data.get('prompt', '')
            img_b64 = data.get('image_b64', '')
            try:
                job_id = wan_queue_ssh(
                    prompt    = prompt,
                    mode      = mode,
                    image_b64 = img_b64 if mode == 'i2v' else None,
                )
                _send_json(self, 200, {'prompt_id': job_id})
            except Exception as e:
                _send_json(self, 500, {'error': str(e)})

        elif self.path == '/api/proxy/sdwebui':
            data     = json.loads(body_raw)
            endpoint = data.pop('_endpoint', 'txt2img')
            sd_url   = f'http://localhost:7860/sdapi/v1/{endpoint}'
            req_body = json.dumps(data).encode()
            req = urllib.request.Request(
                sd_url, data=req_body,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    resp_body = r.read()
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
                _send_json(self, 503, {'error': f'SD WebUI 연결 실패: {str(e)}'})

        elif self.path == '/api/sdwebui/status':
            try:
                with urllib.request.urlopen('http://localhost:7860/sdapi/v1/progress', timeout=3) as r:
                    _send_json(self, 200, {'online': True})
            except Exception:
                _send_json(self, 200, {'online': False})

        else:
            self.send_response(404)
            self.end_headers()

    def _proxy_comfy(self, method, raw_path, body):
        ALLOWED_PREFIXES = ['/system_stats', '/history/', '/view', '/queue', '/prompt', '/object_info']
        parsed    = urllib.parse.urlparse(raw_path)
        # strip the /api/proxy/comfy prefix for GET requests
        comfy_path = parsed.path.replace('/api/proxy/comfy', '', 1) or '/system_stats'
        if comfy_path == '/prompt':
            pass  # POST /prompt is always allowed
        elif not any(comfy_path.startswith(p) for p in ALLOWED_PREFIXES):
            _send_json(self, 400, {'error': 'invalid comfy path'}); return

        comfy_base = load_env().get('COMFY_URL', 'http://localhost:8188').rstrip('/')
        qs         = parsed.query
        url        = f'{comfy_base}{comfy_path}{"?" + qs if qs else ""}'
        headers    = {'User-Agent': 'YouTubeContentTool/1.0'}
        if method == 'POST':
            headers['Content-Type'] = 'application/json'

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                content_type = resp.headers.get('Content-Type', 'application/json')
                resp_body    = resp.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
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
