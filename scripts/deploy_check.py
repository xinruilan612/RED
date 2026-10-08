"""Production preflight. No model calls; DB checks are opt-in and read-only."""
import argparse
import sys
import time
from urllib.parse import urlsplit


def validate(env):
    errors = []
    origin = env.get('PUBLIC_ORIGIN', '')
    database = env.get('DATABASE_URL', '')
    invite = env.get('REGISTRATION_INVITE', '')
    try:
        site = urlsplit(origin)
        valid = (site.scheme == 'https' and site.hostname and
                 site.hostname not in ('localhost', '127.0.0.1', '::1') and
                 not site.username and not site.password and site.port in (None, 443) and
                 site.path == '' and not site.query and not site.fragment and
                 'CHANGE_ME' not in origin and origin == origin.strip())
    except ValueError:
        valid = False
    if not valid:
        errors.append('PUBLIC_ORIGIN must be an HTTPS domain without path or explicit non-443 port.')
    try:
        db = urlsplit(database)
        valid = (db.scheme in ('postgresql', 'postgres') and
                 db.path not in ('', '/') and 'CHANGE_ME' not in database)
    except ValueError:
        valid = False
    if not valid:
        errors.append('DATABASE_URL must point to a dedicated PostgreSQL database; replace placeholders.')
    if len(invite) < 16 or 'CHANGE_ME' in invite or any(c.isspace() for c in invite):
        errors.append('REGISTRATION_INVITE must have at least 16 characters and no whitespace or placeholders.')
    if any(c.isspace() for c in env.get('DEEPSEEK_API_KEY', '')):
        errors.append('DEEPSEEK_API_KEY must not contain whitespace.')
    if env.get('WINDTUNNEL_ALLOW_LIVE', 'false').lower() != 'false':
        errors.append('Keep WINDTUNNEL_ALLOW_LIVE=false for initial deployment acceptance.')
    return errors


def check_database(target, worker=False):
    from backend.database import connect
    with connect(target) as db:
        db.execute('SET TRANSACTION READ ONLY')
        row = db.execute('SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user').fetchone()
        if row is None or any(row):
            raise RuntimeError('Use a dedicated database role without superuser, CREATEDB or CREATEROLE privileges.')
        if worker:
            row = db.execute('SELECT MAX(heartbeat) FROM runtime_workers').fetchone()
            if not row or row[0] is None or not 0 <= time.time() - row[0] <= 45:
                raise RuntimeError('No recent Worker heartbeat; check the separate worker service.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', action='store_true', help='read-only PostgreSQL connectivity/role check')
    parser.add_argument('--worker', action='store_true', help='also require a Worker heartbeat within 45 seconds')
    args = parser.parse_args(argv)
    try:
        from backend.api import settings
        from backend.provider import load_config
        env = settings()
        errors = validate(env)
        if errors:
            for error in errors:
                print('FAIL: ' + error)
            return 1
        load_config(environ=env)  # Validate routes locally; never instantiate a model call.
        if args.database or args.worker:
            try:
                check_database(env['DATABASE_URL'], worker=args.worker)
            except Exception:
                print('FAIL: PostgreSQL role/connectivity or Worker heartbeat check failed; inspect privately on server.')
                return 1
    except Exception:
        print('FAIL: Configuration/dependencies could not be loaded; inspect privately on server.')
        return 1
    print('PASS: production configuration' + (' and PostgreSQL' if args.database or args.worker else '') +
          (' and Worker heartbeat' if args.worker else '') + '; no model calls made.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
