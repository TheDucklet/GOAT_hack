"""Prepare synthetic R07 users only in an empty dedicated database; no existing data changes."""
import json
import sys

sys.path.insert(0, '/srv/backend')
from sqlalchemy import select

from app.cli import seed_demo
from app.db import session_factory
from app.models import Company, Membership, User
from app.services.sessions import hasher

password = json.load(sys.stdin)['password']
with session_factory()() as db, db.begin():
    if db.bind.url.database != 'goat_r07':
        raise SystemExit('Use only the dedicated goat_r07 acceptance database')
    if db.scalar(select(User.id).limit(1)) or db.scalar(select(Company.id).limit(1)):
        raise SystemExit('Use a fresh empty R07 database; existing records are never replaced')
    seed_demo(db, password)
    db.flush()
    users = {user.email: user for user in db.scalars(select(User))}
    for email, company, position in [
        ('user_a@goat.example.org', 'demo_company_a', 'Финансовый директор'),
        ('user_b@goat.example.org', 'demo_company_b', 'Руководитель нового направления'),
    ]:
        membership = db.scalar(select(Membership).where(Membership.user_id == users[email].id, Membership.company_id == company))
        membership.position_text = position
    for email, company, position in [
        ('user_b@goat.example.org', 'demo_company_a', 'Генеральный директор / международное развитие'),
        ('user_a@goat.example.org', 'demo_company_b', 'Финансовый директор'),
    ]:
        db.add(Membership(user_id=users[email].id, company_id=company, status='pending', position_text=position, interests=['Денежные потоки']))
    rejected = User(email='r07-request@example.org', password_hash=hasher.hash(password))
    db.add(rejected)
    db.flush()
    db.add(Membership(user_id=rejected.id, company_id='demo_company_a', status='pending', position_text='Любая должность', interests=[]))
print(json.dumps({'result': 'seeded', 'synthetic': True}))
