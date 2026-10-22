"""R09 acceptance fixture; only a fresh dedicated database, no external AI."""
import copy
import json
import runpy
import sys

sys.path.insert(0, '/srv/backend')
from sqlalchemy import func, select

from app.db import session_factory
from app.models import DemoAction, Feedback, FeedDismissal, Insight, Membership, ProductEvent, User
from app.services.sessions import hasher

action = sys.argv[1]
if action == 'seed':
    # The seed consumes stdin; capture once and supply it to the shared fixture.
    import io
    payload = sys.stdin.read()
    sys.stdin = io.StringIO(payload)
    runpy.run_path('/srv/r05/insight_fixture.py', run_name='__main__')
with session_factory()() as db, db.begin():
    if db.bind.url.database != 'goat_r09':
        raise SystemExit('Use only the dedicated goat_r09 database')
    if action == 'seed':
        password = json.loads(payload)['password']
        db.add(User(id='r09-other', email='r09-other@example.org', password_hash=hasher.hash(password)))
        db.flush()
        db.add(Membership(user_id='r09-other', company_id='r05-company-a', status='active', position_text='Генеральный директор', interests=[]))
        db.add(Membership(user_id='r05-user', company_id='r05-company-b', status='active', position_text='Руководитель', interests=[]))
        card = db.get(Insight, 'r05-insight-historical')
        result = copy.deepcopy(card.result)
        result['facts'][0]['text'] += ' <script>window.__r09Xss=true</script>'
        card.result = result
    elif action == 'counts':
        counts = {name: db.scalar(select(func.count()).select_from(model)) for name, model in [('feedback', Feedback), ('demo', DemoAction), ('dismissals', FeedDismissal)]}
        counts['product_events'] = [{'kind': row.event_type, 'excluded_reason': row.excluded_reason, 'user_id': row.user_id} for row in db.scalars(select(ProductEvent))]
        print(json.dumps(counts))
    else:
        raise SystemExit('Unknown fixture action')
