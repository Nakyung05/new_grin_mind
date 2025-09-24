import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, request, jsonify, g
from flask_cors import CORS
import jwt
from werkzeug.security import generate_password_hash, check_password_hash

# --- 환경 변수 설정 ---
# Railway 배포 환경에서 자동으로 설정해주는 값들을 읽어옵니다.
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-jwt-change-me")
DATABASE_URL = os.getenv("DATABASE_URL") # Railway의 PostgreSQL 주소

TOKEN_EXPIRE_HOURS = 24 * 7

# --- Flask 앱 초기화 ---
# Flutter 빌드 결과물이 담길 'static' 폴더를 지정합니다.
app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app, resources={r"/api/*": {"origins": "*"}})

# --- 데이터베이스 연결 관리 ---
def get_db():
    if 'db' not in g:
        # PostgreSQL에 연결합니다.
        g.db = psycopg2.connect(DATABASE_URL)
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# --- 데이터베이스 테이블 초기화 ---
def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    # PostgreSQL 문법에 맞게 SQL 수정
    # id 필드를 SERIAL PRIMARY KEY로 변경 (자동 증가)
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS actions(
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS action_logs(
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            action_id INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )""")
        defaults = [('텀블러 사용',), ('분리수거 철저',), ('대중교통 이용',),
                    ('일회용품 줄이기',), ('에너지 절약',), ('채식 식사 선택',), ('재사용·수리하기',)]
        # ON CONFLICT (name) DO NOTHING: 중복된 이름이 있으면 무시
        cur.executemany("INSERT INTO actions(name) VALUES(%s) ON CONFLICT (name) DO NOTHING", defaults)
    conn.commit()
    conn.close()


# --- JWT 토큰 및 인증 관련 함수 ---
def create_token(user_id, email):
    payload = {
        'sub': user_id,
        'email': email,
        'exp': datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def get_current_user_id():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth.split(' ', 1)[1]
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        return data.get('sub')
    except Exception:
        return None

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        uid = get_current_user_id()
        if not uid:
            return jsonify({'error': 'unauthorized'}), 401
        g.user_id = uid
        return f(*args, **kwargs)
    return wrapper

# --- 시간 관련 유틸리티 함수 ---
KST = timezone(timedelta(hours=9))

def monday_00(dt):
    return (dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

def week_ranges_for_today(now=None):
    now = now.astimezone(KST) if now else datetime.now(KST)
    this_mon = monday_00(now)
    last_mon = this_mon - timedelta(days=7)
    last_sun_2359 = this_mon - timedelta(seconds=1)
    if now.weekday() == 0: # 월요일인 경우
        lb_start, lb_end = last_mon, last_sun_2359
        period_label = 'last_week'
    else:
        lb_start, lb_end = this_mon, now
        period_label = 'this_week'
    me_start, me_end = this_mon, now
    return (lb_start, lb_end, period_label, me_start, me_end)

# --- API 엔드포인트 ---
@app.post('/api/signup')
def signup():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not email or not password:
        return jsonify({'error': 'email and password required'}), 400
    
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("INSERT INTO users(email, password_hash) VALUES(%s, %s)",
                        (email, generate_password_hash(password)))
        db.commit()
        return jsonify({'ok': True})
    except psycopg2.IntegrityError:
        db.rollback()
        return jsonify({'error': 'email exists'}), 409

@app.post('/api/login')
def login():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT id, password_hash FROM users WHERE email=%s", (email,))
        row = cur.fetchone()
    
    if not row or not check_password_hash(row['password_hash'], password):
        return jsonify({'error': 'invalid credentials'}), 401
    
    token = create_token(row['id'], email)
    return jsonify({'token': token})

@app.get('/api/actions')
@login_required
def list_actions():
    _, _, _, me_start, me_end = week_ranges_for_today()
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("""
            SELECT a.id, a.name,
                   COALESCE(SUM(CASE WHEN l.created_at BETWEEN %s AND %s THEN l.delta END), 0) AS count
            FROM actions a
            LEFT JOIN action_logs l ON l.action_id=a.id AND l.user_id=%s
            GROUP BY a.id, a.name
            ORDER BY a.id ASC
        """, (me_start, me_end, g.user_id))
        rows = cur.fetchall()
    items = [{'id': r['id'], 'name': r['name'], 'count': int(r['count'] or 0)} for r in rows]
    return jsonify({'items': items})

@app.post('/api/actions/<int:action_id>/add')
@login_required
def add_action(action_id):
    data = request.get_json() or {}
    delta = int(data.get('delta') or 0)
    if delta not in (-1, 1):
        return jsonify({'error': 'delta must be -1 or 1'}), 400
    
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM actions WHERE id=%s", (action_id,))
        if not cur.fetchone():
            return jsonify({'error': 'action not found'}), 404
        
        cur.execute(
            "INSERT INTO action_logs(user_id, action_id, delta) VALUES(%s, %s, %s)",
            (g.user_id, action_id, delta)
        )
    db.commit()
    return jsonify({'ok': True})

@app.get('/api/leaderboard')
@login_required
def leaderboard():
    lb_start, lb_end, period_label, me_start, me_end = week_ranges_for_today()
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        # 리더보드 순위 계산
        cur.execute("""
            SELECT u.id AS user_id, u.email, COALESCE(SUM(l.delta), 0) AS total
            FROM users u
            LEFT JOIN action_logs l
              ON l.user_id=u.id AND l.created_at BETWEEN %s AND %s
            GROUP BY u.id, u.email
            ORDER BY total DESC, u.id ASC
        """, (lb_start, lb_end))
        rows = cur.fetchall()
        items = [{'email': r['email'], 'weeklyTotal': int(r['total'] or 0)} for r in rows]

        # 내 정보 찾기
        cur.execute("SELECT email FROM users WHERE id=%s", (g.user_id,))
        my_email = cur.fetchone()['email']
        
        my_rank = None
        for i, r in enumerate(items, start=1):
            if r['email'] == my_email:
                my_rank = i
                break

        # 이번 주 내 실천 수
        cur.execute("""
            SELECT COALESCE(SUM(delta), 0) AS total
            FROM action_logs
            WHERE user_id=%s AND created_at BETWEEN %s AND %s
        """, (g.user_id, me_start, me_end))
        r = cur.fetchone()
        my_total = int(r['total'] or 0)

    return jsonify({
        'leaderboard': items,
        'me': {'rank': my_rank, 'weeklyTotal': my_total}
    })

# --- 서버 시작 시 DB 초기화 ---
with app.app_context():
    init_db()

# --- Flutter 웹 앱 제공 ---
# API 경로가 아닌 모든 요청을 Flutter 앱의 index.html로 전달합니다.
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_flutter(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return app.send_static_file(path)
    else:
        return app.send_static_file('index.html')

# --- 메인 실행 ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)