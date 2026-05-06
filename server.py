#!/usr/bin/env python3
"""
로컬 서버 — .env 파일로 API 키를 관리합니다.
실행: python3 server.py
접속: http://localhost:8765
"""
import json, os, urllib.request, urllib.parse, urllib.error
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ENV_FILE   = Path(__file__).parent / '.env'
SKILLS_DIR = Path(__file__).parent / 'claude-youtube-main/skills/claude-youtube'
YT_SKILLS_DIR = Path(__file__).parent / 'youtube-skills-main/skills'

def load_env():
    keys = {
        'YOUTUBE_API_KEY': '',
        'GEMINI_API_KEY': '',
        'GEMINI_MODEL': 'gemini-2.5-flash',
        'TRANSCRIPT_API_KEY': '',
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
    )
    ENV_FILE.write_text(content, encoding='utf-8')

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
