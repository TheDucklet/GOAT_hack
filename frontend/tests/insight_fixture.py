"""Synthetic saved v1/v2 cards and PDF for the isolated goat_r05 database only."""
import copy
import hashlib
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, '/srv/backend')

from pypdf import PdfWriter
from sqlalchemy import select

from app.config import get_settings
from app.data_semantics import DATA_SEMANTICS_VERSION, normalize_feature
from app.db import session_factory, utcnow
from app.models import BankDocument, Company, Event, Evidence, Insight, Membership, News, Source, User
from app.schemas import parse_insight_result
from app.services.insights import insight_versions
from app.services.sessions import hasher

COMPANY = 'r05-company-a'
with session_factory()() as db, db.begin():
    if db.bind.url.database != 'goat_r05':
        raise SystemExit('Only the dedicated goat_r05 acceptance database is allowed')
    if sys.argv[1] == 'stale':
        db.get(Company, COMPANY).profile_version = 'r05-changed-profile'
    elif sys.argv[1] == 'seed':
        if db.scalar(select(User.id).limit(1)) or db.scalar(select(Event.id).limit(1)):
            raise SystemExit('Use a fresh isolated R05 database; existing records are never replaced')
        password = json.load(sys.stdin)['password']
        values = {'CL_TYPE': 'CLIENT', 'MAINOKVED_CODE': '25.61', 'CL_PRODUCT_LOA_MARK': '1.0'}
        for name in [COMPANY, 'r05-company-b']:
            features = {key: normalize_feature(key, [(1, values)], 'synthetic-r05') for key in values}
            features['confirmed_floating_debt'] = {
                'value': '1000000 RUB; плавающая ставка; пересмотр 01.11.2026',
                'quality': 'confirmed', 'provenance': {'file': 'synthetic-r05', 'synthetic': True},
            }
            db.add(Company(id=name, name='Учебная компания ' + name[-1].upper(), profile_version='r05-v2',
                           data_semantics_version=DATA_SEMANTICS_VERSION, identity_quality='confirmed', client_type='Client',
                           features=features))
        user = User(id='r05-user', email='r05-insight@example.org', password_hash=hasher.hash(password))
        db.add(user)
        db.add(Source(id='r05-source', name='Учебные новости', feed_url='https://example.org/rss', allowed_hosts=['example.org']))
        db.flush()
        db.add(Membership(user_id=user.id, company_id=COMPANY, status='active', position_text='Финансовый директор', interests=[]))
        db.flush()
        # A real readable PDF; blank pages are explicitly synthetic, not an actual bank position.
        storage = get_settings().storage_dir
        storage.mkdir(parents=True, exist_ok=True)
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=300, height=400)
        path = storage / 'r05-synthetic.pdf'
        writer.write(str(path))
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        db.add(BankDocument(id='r05-document', filename=path.name, sha256=sha, version=sha,
                            index_version='r05-synthetic', document_date='2024-06-01', storage_key=path.name, page_count=3, status='done'))
        db.flush()
        examples = json.loads(Path('/srv/docs/contracts/insight-v2-examples.json').read_text(encoding='utf-8'))
        cases = [('historical', 'historical_bank_position', 'Учебная карточка: исторический банк'),
                 ('missing', 'missing_bank_position', 'Учебная карточка: без позиции банка'),
                 ('legacy', 'historical_bank_position', 'Учебная карточка: старая версия v1'),
                 ('queued', None, 'Учебная карточка: фоновое задание')]
        for suffix, example_name, title in cases:
            event_id = 'r05-event-' + suffix
            db.add(Event(id=event_id, title=title, normalized_title=title.lower(), summary='Синтетические данные для проверки UI R-05.',
                         published_at=utcnow(), topics={'industry': ['25.61']}, processing_status='done'))
            db.flush()
            news_id = 'r05-news-' + suffix
            publication = News(id=news_id, source_id='r05-source', event_id=event_id, title=title,
                               text='Учебное изменение условий кредитования. Не является реальной новостью.',
                               url='https://example.org/synthetic/' + suffix, content_hash='r05-news-version-' + suffix, published_at=utcnow())
            db.add(publication)
            db.flush()
            if example_name is None:
                db.add(Evidence(id='r05-queued-news', kind='news', source_id=news_id, version=publication.content_hash,
                                locator={'url': publication.url}, excerpt=publication.text))
                continue
            envelope = copy.deepcopy(next(item['envelope'] for item in examples if item['name'] == example_name))
            mapping = {item['id']: 'r05-' + suffix + '-' + item['id'] for item in envelope['evidence']}

            def remap(value):
                if isinstance(value, dict):
                    return {key: remap(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [remap(item) for item in value]
                return mapping.get(value, value) if isinstance(value, str) else value

            result = remap(envelope['result'])
            result['trace_id'] = str(uuid4())
            if suffix == 'legacy':
                fields = ['facts', 'bank_view', 'ai_interpretation', 'risks', 'opportunities', 'actions', 'unknowns', 'evidence_refs', 'trace_id']
                result = {key: result[key] for key in fields}
                for key in fields[:6]:
                    if result[key] is not None:
                        result[key] = [{field: claim[field] for field in ('claim_id', 'text', 'evidence_refs')} for claim in result[key]]
            result = parse_insight_result(result).model_dump(mode='json')
            for item in envelope['evidence']:
                locator = dict(item['locator'])
                source_id, version = item['source_id'], item['version']
                if item['kind'] == 'bank':
                    source_id, version = 'r05-document', sha
                elif item['kind'] == 'news':
                    source_id, version = news_id, publication.content_hash
                    locator['url'] = publication.url
                else:
                    source_id, version = COMPANY, 'r05-v2'
                    locator.update(feature_path='features.confirmed_floating_debt', value=db.get(Company, COMPANY).features['confirmed_floating_debt'])
                db.add(Evidence(id=mapping[item['id']], kind=item['kind'], source_id=source_id, version=version,
                                company_id=COMPANY if item['kind'] == 'company' else None, locator=locator, excerpt=item['excerpt']))
            versions, key = insight_versions(db, user, COMPANY, event_id)
            db.add(Insight(id='r05-insight-' + suffix, user_id=user.id, company_id=COMPANY, event_id=event_id,
                           cache_key=key, versions=versions, result=result))
        db.add(Evidence(id='r05-foreign-source', kind='company', source_id='r05-company-b', company_id='r05-company-b',
                        version='r05-v2', locator={'feature_path': 'features.MAINOKVED_CODE'}, excerpt='PRIVATE SYNTHETIC DATA'))
    else:
        raise SystemExit('Unknown fixture operation')
print(json.dumps({'result': 'PASS', 'kind': 'synthetic R05 fixture'}))
