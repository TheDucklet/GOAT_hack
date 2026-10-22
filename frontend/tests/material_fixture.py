"""R08 isolated synthetic account/news/failure fixtures; real provided PDF is uploaded separately."""
import json
import sys

sys.path.insert(0, '/srv/backend')
from sqlalchemy import func, select

from app.cli import seed_demo
from app.db import session_factory
from app.models import BankDocument, Chunk, Company, Event, Job, User
from tests.factories import event_fixture

action = sys.argv[1]
with session_factory()() as db, db.begin():
    if db.bind.url.database != 'goat_r08':
        raise SystemExit('Only the dedicated goat_r08 database is allowed')
    if action == 'seed':
        if db.scalar(select(User.id).limit(1)) or db.scalar(select(Company.id).limit(1)):
            raise SystemExit('Use an empty R08 database; existing records are never changed')
        seed_demo(db, json.load(sys.stdin)['password'])
        db.add(BankDocument(id='r08-missing-file', filename='Учебная ошибка PDF.pdf', sha256='e' * 64, version='e' * 64,
                            storage_key='r08-intentionally-missing.pdf', page_count=1, status='failed', error='not_found'))
    elif action == 'counts':
        print(json.dumps({'jobs': db.scalar(select(func.count()).select_from(Job)),
                          'chunks': db.scalar(select(func.count()).select_from(Chunk)),
                          'documents': db.scalar(select(func.count()).select_from(BankDocument))}))
    else:
        raise SystemExit('Unknown fixture action')
if action == 'seed':
    event_id = event_fixture()
    with session_factory()() as db, db.begin():
        event = db.get(Event, event_id)
        event.title = 'Учебная новость R-08'
        event.summary = 'Синтетическое событие для проверки глобальной видимости.'
        event.processing_status = 'done'
        event.topics = {'industry': ['25.61']}
    print(json.dumps({'event_id': event_id}))
