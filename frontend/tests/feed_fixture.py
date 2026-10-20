"""Synthetic R-04 data. Called inside the API container by feed_smoke.py.

Requires a dedicated empty acceptance database; never touches existing events.
"""
import json
import sys
from datetime import timedelta

from sqlalchemy import select

from app.db import session_factory, utcnow
from app.models import Company, Event, Membership, News, Source, User
from app.services.sessions import hasher

PREFIX = 'r04-acceptance-'
action = sys.argv[1]
with session_factory()() as db:
    if action == 'seed':
        if db.scalar(select(Event.id).limit(1)) or db.scalar(select(User.id).limit(1)):
            raise SystemExit('Use a fresh, dedicated acceptance database without users or events.')
        password = json.load(sys.stdin)['password']
        user = User(id=PREFIX + 'user', email='r04-feed@example.org', password_hash=hasher.hash(password))
        db.add(user)
        for suffix, industry, city in [('a', '25.61', 'Москва'), ('b', '62.01', 'Казань')]:
            company_id = PREFIX + suffix
            db.add(Company(id=company_id, name=f'Тестовая компания {suffix.upper()}', profile_version='r04-v1', features={
                'MAINOKVED_CODE': {'value': industry, 'source': {'table': 'synthetic'}},
                'CITY': {'value': city, 'source': {'table': 'synthetic'}},
            }))
            db.flush()
            db.add(Membership(user_id=user.id, company_id=company_id, status='active', position_text='Руководитель', interests=['расчёты']))
        db.add(Source(id=PREFIX + 'source', name='Синтетические новости R-04', feed_url='https://example.org/feed', allowed_hosts=['example.org']))
        db.flush()
        for number in range(25):
            event_id = PREFIX + f'{number:02d}'
            title = f'Тестовое событие {number:02d}'
            db.add(Event(id=event_id, title=title, normalized_title=title.lower(),
                         summary=f'Изменение условий расчётов: пример {number:02d}.', published_at=utcnow() - timedelta(minutes=number),
                         topics={'industry': ['25.61'] if number < 12 else ['62.01']}, processing_status='done'))
            db.flush()
            db.add(News(source_id=PREFIX + 'source', event_id=event_id,
                        url=f'https://example.org/r04/{number}', title=title, text=title,
                        content_hash=event_id, published_at=utcnow() - timedelta(minutes=number)))
    elif action == 'update':
        event = db.get(Event, PREFIX + '00')
        event.title = 'Новость обновлена в backend'
        event.summary = 'Изменение из PostgreSQL видно в интерфейсе.'
    elif action in {'hide', 'show'}:
        events = list(db.scalars(select(Event).where(Event.id.startswith(PREFIX))))
        for event in events:
            event.visible = action == 'show'
    else:
        raise SystemExit('Unknown fixture action.')
    db.commit()
print(json.dumps({'action': action, 'result': 'PASS'}))
