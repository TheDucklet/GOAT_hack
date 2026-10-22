"""Explicit synthetic chat producer for browser integration only. No gateway calls."""
from uuid import uuid4

from app.integrations.ai import AIError
from tests.fake_ai import derive_user_focus as derive_user_focus
from tests.fake_feed_ai import build_insight as build_insight

attempts = {}


def answer_chat(company_context, user_focus, event, history, tools):
    assert tools.get_company_context()['company_id'] == company_context['company_id']
    assert tools.get_event()['id'] == event['id']
    question = history[-1]['text']
    attempts[question] = attempts.get(question, 0) + 1
    if question == 'Учебный бюджетный отказ' and attempts[question] == 1:
        raise AIError('budget_exhausted', 'Учебный отказ бюджета; внешний шлюз не вызывался')
    return {
        'result': {
            'answer': 'Учебный условный ответ: ' + question,
            'evidence_refs': ['r05-historical-bank-2024', event['evidence'][0]['id']],
            'unknowns': ['Учебное ограничение: сумма и условия требуют уточнения'],
            'trace_id': str(uuid4()),
            'usage': {'llm_calls': 0},
        },
        'evidence': [],
        'trace': {'mode': 'r06-synthetic', 'history_turns': len(history)},
    }
