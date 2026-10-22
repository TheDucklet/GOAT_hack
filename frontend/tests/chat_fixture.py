"""Extend the shared R05 synthetic seed for R06; never touches an existing user DB."""
import json
import runpy
import sys
from datetime import timedelta

sys.path.insert(0, '/srv/backend')
from sqlalchemy import select

from app.db import session_factory, utcnow
from app.models import LoginSession, Membership, Message, User

action = sys.argv[1]
if action == 'seed':
    runpy.run_path('/srv/r05/insight_fixture.py', run_name='__main__')
with session_factory()() as db, db.begin():
    if db.bind.url.database != 'goat_r06':
        raise SystemExit('Use only the dedicated goat_r06 database')
    user = db.scalar(select(User).where(User.email == 'r05-insight@example.org'))
    if action == 'seed':
        db.add(Membership(user_id=user.id, company_id='r05-company-b', status='active', position_text='Руководитель', interests=[]))
    elif action == 'expire-session':
        for session in db.scalars(select(LoginSession).where(LoginSession.user_id == user.id)):
            session.expires_at = utcnow() - timedelta(minutes=1)
    elif action == 'counts':
        rows = list(db.scalars(select(Message).order_by(Message.chat_id, Message.sequence)))
        print(json.dumps({'user': sum(row.role == 'user' for row in rows), 'assistant': sum(row.role == 'assistant' for row in rows)}))
    elif action != 'seed':
        raise SystemExit('Unknown fixture operation')
