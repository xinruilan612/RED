"""Password accounts, revocable opaque sessions and explicit legacy-space claim."""
import hashlib
import hmac
import re
import secrets
import time
from uuid import uuid4
from backend.contracts import require


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    require(isinstance(password, str) and 12 <= len(password) <= 128, 'INVALID_INPUT', '密码需为 12 至 128 个字符')
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()


def verify(password, encoded):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        return False
    return hmac.compare_digest(password_hash(password, encoded.split(':')[0]), encoded)


class Auth:
    def __init__(self, store):
        self.store = store
        self.dummy = password_hash('not-a-real-password')
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, owner TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL, recovery_hash TEXT NOT NULL, created_at BIGINT NOT NULL);
                CREATE TABLE IF NOT EXISTS web_sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), csrf TEXT NOT NULL,
                    expires_at BIGINT NOT NULL);
                CREATE TABLE IF NOT EXISTS auth_limits (
                    bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, reset_at BIGINT NOT NULL);
            ''')

    def throttle(self, bucket, limit=12, seconds=900):
        now = int(time.time())
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM auth_limits WHERE reset_at<?', (now,))
            key = hashed(bucket)
            row = db.execute('SELECT count FROM auth_limits WHERE bucket=?', (key,)).fetchone()
            require(not row or row[0] < limit, 'RATE_LIMITED', '请求过于频繁，请稍后再试')
            db.execute('INSERT INTO auth_limits VALUES(?,?,?) ON CONFLICT(bucket) DO UPDATE SET count=auth_limits.count+1', (key,1,now+seconds))

    def session(self, token):
        with self.store.connect() as db:
            row = db.execute('SELECT s.csrf,u.id,u.username,u.owner FROM web_sessions s LEFT JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?', (hashed(token),int(time.time()))).fetchone()
        return dict(csrf=row[0],user=dict(id=row[1],username=row[2]) if row[1] else None,owner=row[3]) if row else None

    def issue(self, user_id=None, previous=''):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.store.connect() as db:
            db.execute('DELETE FROM web_sessions WHERE token_hash=? OR expires_at<=?', (hashed(previous),int(time.time())))
            db.execute('INSERT INTO web_sessions VALUES(?,?,?,?)', (hashed(token),user_id,csrf,int(time.time())+(604800 if user_id else 3600)))
        return token

    def logout(self, token):
        with self.store.connect() as db:
            db.execute('DELETE FROM web_sessions WHERE token_hash=?', (hashed(token),))

    def register(self, data, legacy_token='', invite=''):
        require(set(data) <= {'username','password','invite','claim_legacy'} and {'username','password'} <= set(data), 'INVALID_INPUT', '注册字段无效')
        name = data['username']
        require(isinstance(name,str) and re.fullmatch(r'[a-zA-Z0-9_]{3,40}',name), 'INVALID_INPUT', '用户名为 3 至 40 位英文字母、数字或下划线')
        require(type(data.get('claim_legacy',False)) is bool, 'INVALID_INPUT', '迁移选择无效')
        require(not invite or (isinstance(data.get('invite'),str) and hmac.compare_digest(data['invite'],invite)), 'FORBIDDEN', '邀请码无效')
        encoded = password_hash(data['password'])
        user_id, recovery = str(uuid4()), secrets.token_urlsafe(32)
        owner = user_id
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            require(not db.execute('SELECT 1 FROM users WHERE username=?',(name.lower(),)).fetchone(), 'DUPLICATE', '此用户名不可用')
            if data.get('claim_legacy') and legacy_token and db.has_table('demo_sessions'):
                old = db.execute('SELECT owner FROM demo_sessions WHERE token_hash=?',(hashed(legacy_token),)).fetchone()
                if old:
                    require(not db.execute('SELECT 1 FROM users WHERE owner=?',(old[0],)).fetchone(), 'SPACE_CLAIMED', '该旧空间已绑定网站用户，请登录原用户')
                    owner = old[0]
            db.execute('INSERT INTO users VALUES(?,?,?,?,?,?)',(user_id,name.lower(),owner,encoded,hashed(recovery),int(time.time())))
        return user_id, recovery

    def login(self, data):
        require(set(data)=={'username','password'} and isinstance(data['username'],str), 'INVALID_INPUT', '登录字段无效')
        with self.store.connect() as db:
            row = db.execute('SELECT id,password_hash FROM users WHERE username=?',(data['username'].lower(),)).fetchone()
        ok = verify(data['password'], row[1] if row else self.dummy)
        require(ok and row, 'AUTH_REQUIRED', '用户名或密码不正确')
        return row[0]

    def reset(self, data):
        require(set(data)=={'username','password','recovery_code'} and isinstance(data['username'],str) and isinstance(data['recovery_code'],str), 'INVALID_INPUT', '恢复字段无效')
        encoded = password_hash(data['password'])
        fresh = secrets.token_urlsafe(32)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id,recovery_hash FROM users WHERE username=?',(data['username'].lower(),)).fetchone()
            require(row and hmac.compare_digest(row[1],hashed(data['recovery_code'])), 'AUTH_REQUIRED', '用户名或恢复码不正确')
            db.execute('UPDATE users SET password_hash=?,recovery_hash=? WHERE id=?',(encoded,hashed(fresh),row[0]))
            db.execute('DELETE FROM web_sessions WHERE user_id=?',(row[0],))
        return row[0], fresh
