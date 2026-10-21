"""Validate one planning catalogue and render Markdown, HTML and optional PDFs.

Run from any directory: python scripts/render_planning.py [--check | --no-pdf].
PDF export needs Playwright and PyMuPDF on the host; no application dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CATALOGUE = REPO / 'docs/planning/plan.json'
OUT = REPO.parent / 'output/planning'
LABELS = {'done': 'Закрыта исходная постановка', 'new': 'Новая задача', 'revised': 'Изменена нерешённая задача'}
NOTICE = 'Материал подготовлен с использованием ИИ, носит информационный характер и не является индивидуальной инвестиционной рекомендацией. Выводы ИИ не являются официальной позицией банка.'


def deadline(task):
    match = re.search(r'(\d{2})\.(\d{2}), (\d{2}):(\d{2})', task['due'])
    if not match:
        raise ValueError(f'Missing deadline: {task["code"]}')
    day, month, hour, minute = map(int, match.groups())
    return datetime(2026, month, day, hour, minute)


def active(plan, person):
    return sorted((task for task in plan['tasks'][person] if task['status'] != 'done'), key=deadline)


def validate(plan):
    tasks = [task for group in plan['tasks'].values() for task in group]
    by_id = {task['code']: task for task in tasks}
    assert len(by_id) == len(tasks), 'Duplicate task IDs'
    assert set(plan['people']) == set(plan['tasks']), 'Owner mismatch'
    assert all(code in by_id and by_id[code]['status'] == 'done' for code in plan['baseline_done_ids']), 'Baseline closure changed'
    visiting, visited = set(), set()

    def visit(code):
        if code in visiting:
            raise ValueError(f'Dependency cycle at {code}')
        if code in visited:
            return
        visiting.add(code)
        for parent in by_id[code]['dependencies']:
            assert parent in by_id, f'Unknown dependency {parent}'
            visit(parent)
            if by_id[code]['status'] != 'done' and by_id[parent]['status'] != 'done':
                assert deadline(by_id[parent]) <= deadline(by_id[code]), f'Deadline inversion: {parent} -> {code}'
        visiting.remove(code)
        visited.add(code)

    for person, group in plan['tasks'].items():
        for task in group:
            assert task['status'] in LABELS, task['code']
            assert all(task[field] for field in ['title', 'due', 'needs', 'steps', 'deliverables', 'checks', 'commit']), task['code']
            assert set(task['sources']) <= set(plan['sources']), task['code']
            assert all(code in by_id for code in task.get('extends', [])), task['code']
            if task['status'] == 'done':
                assert task['evidence'], f'Closure without evidence: {task["code"]}'
            else:
                assert task['priority'] in {'P0', 'P1', 'P2'}, task['code']
                assert deadline(task) >= datetime(2026, 10, 22), task['code']
            visit(task['code'])
    assert len(plan['criteria']) == 12 and len(plan['scenarios']) == 14
    for _, _, codes in plan['criteria']:
        assert all(code in by_id for code in codes.split(','))
    history = OUT / 'archive/2026-10-19/source/tasks.json'
    preserved = 0
    if history.exists():
        for group in json.loads(history.read_text(encoding='utf-8')).values():
            for original in group:
                current = by_id[original['code']]
                if original['code'] in plan['baseline_done_ids']:
                    assert all(current[key] == value for key, value in original.items()), f'Closed task rewritten: {original["code"]}'
                    preserved += 1
    return {
        'result': 'PASS', 'baseline_sha': plan['baseline_sha'], 'catalogue_sha256': hashlib.sha256(CATALOGUE.read_bytes()).hexdigest(),
        'total': len(tasks), 'done': sum(t['status'] == 'done' for t in tasks),
        'new': sum(t['status'] == 'new' for t in tasks), 'revised': sum(t['status'] == 'revised' for t in tasks),
        'closed_original_records_preserved': preserved, 'dependency_cycles': 0, 'deadline_inversions': 0,
        'criteria': len(plan['criteria']), 'acceptance_scenarios': len(plan['scenarios']),
    }


def table_md(headings, rows):
    return '\n'.join(['| ' + ' | '.join(headings) + ' |', '| ' + ' | '.join('---' for _ in headings) + ' |'] +
                     ['| ' + ' | '.join(str(cell).replace('|', '/') for cell in row) + ' |' for row in rows])


def task_md(task):
    result = [f'### {task["code"]}. {task["title"]}', '',
              f'**Статус:** {LABELS[task["status"]]}. **Приоритет:** {task["priority"]}. **Срок:** {task["due"]} МСК.', '']
    if task.get('original_due'):
        result += [f'Прежний срок: {task["original_due"]}. Новая дата — внутренний срок команды.', '']
    if task.get('extends'):
        result += ['Дополняет закрытые задачи: ' + ', '.join(task['extends']) + '.', '']
    result += ['**Зависимости:** ' + (', '.join(task['dependencies']) or 'уже готовые компоненты, новых блокеров нет') + '.', '',
               '**Условия:** ' + task['needs'], '', '**Что сделать:**', '']
    result += [f'{number}. {step}' for number, step in enumerate(task['steps'], 1)]
    result += ['', '**Результат в коммите:**', ''] + ['- ' + item for item in task['deliverables']]
    result += ['', '**Приёмка:**', ''] + [f'{number}. {check}' for number, check in enumerate(task['checks'], 1)]
    result += ['', f'**Коммит:** `{task["commit"]}`. **Основания:** ' + ', '.join(task['sources']) + '.', '']
    return '\n'.join(result)


def person_md(plan, person):
    info = plan['people'][person]
    pending = active(plan, person)
    closed = [task for task in plan['tasks'][person] if task['status'] == 'done']
    result = [f'# {info["name"]} — задачи после вебинара', '', f'Редакция 21.10.2026 · МСК · baseline `{plan["baseline_sha"]}`.', '', info['scope'] + '.', '', info['reviewer'], '',
              f'Закрыто: {len(closed)}. В работе по новому плану: {len(pending)}. Оценка чистого времени: {sum(t["estimate_hours"] for t in pending)} ч; это ориентир, без гарантии отсутствия интеграционных дефектов.', '',
              table_md(['ID', 'Срок МСК', 'Приоритет', 'Результат'], [(t['code'], t['due'], t['priority'], t['title']) for t in pending]), '', '## Подробные задачи', '']
    result += [task_md(task) for task in pending]
    result += ['## Уже сделано — повторно не назначается', '', plan['closure_note'], '',
               table_md(['ID', 'Исходный результат', 'Историческое подтверждение'], [(t['code'], t['title'], ', '.join(t['evidence'])) for t in closed]), '']
    return '\n'.join(result)


def review_md(plan):
    result = ['# Пересмотр плана по анализу вебинара', '', f'21.10.2026 · МСК · main `{plan["baseline_sha"]}`.', '',
              'Источник истины для новых задач — [plan.json](plan.json). Общий список — [TASKS.md](../../TASKS.md), персональные планы: [Роман](roman.md), [Алексей](alexey.md), [Фёдор](fedor.md). PDF находятся в рабочем каталоге `output/planning/`; прежняя редакция — `output/planning/archive/2026-10-19/`.', '',
              '## Что подтверждено сейчас', '', plan['closure_note'], '',
              table_md(['Участник', 'Исходные задачи закрыты', 'Изменены нерешённые', 'Новые продолжения'], [
                  ['Роман', 'R-00–R-04', 'R-05–R-12', 'R-13–R-14'], ['Алексей', 'A-01–A-13', 'нет', 'A-14–A-18'], ['Фёдор', 'F-01–F-12', 'нет', 'F-13–F-17']]), '',
              'Код и артефакты приёмки просмотрены; новый полный тестовый прогон приложения в рамках изменения плана не запускался. В частности, импорт всего платёжного CSV уже подтверждён `docs/qa/real-snapshot.json` (1 380 585 строк), а AI S1–S8/OCR/RAG имеют записи в `docs/quality/`. Новые задачи углубляют семантику и продуктовую приёмку, а не требуют повторить готовые модули.', '',
              'В `docs/quality/ai-evaluation.md` зафиксированы реальные ограничения: S5 допускает пресуппозицию о «существующих кредитах» при неполном профиле, дата старого банковского документа не всегда попадает в текст. Это основание F-15 независимо от точности пересказа вебинара.', '',
              '## Решения и изменения приоритетов', '']
    result += ['- ' + item for item in plan['decisions']]
    result += ['', 'В исходном кейсе административный продукт и отдельное мобильное приложение не указаны обязательными самостоятельными результатами. Поэтому готовый backend/auth не удаляем, а UI администрирования ограничиваем операторским минимумом. Собственная многошаговая агентная логика обязательна по стр. 7 и критерию 11; неоднозначный пересказ не отменяет это требование.', '',
               'Восемь нерешённых задач Романа переписаны: R-05 — влияние/evidence/notice; R-06 — живой чат и те же ограничения; R-07/R-08 — минимальная админка; R-09 — персональные действия/feedback и базовая адаптивность; R-10 — 14 end-to-end сценариев; R-11 — новый release gate/manifest; R-12 — CJM, продуктовая демонстрация и подтверждённый срок сдачи.', '',
               '## План передачи результатов', '', table_md(['Срок МСК', 'Кто', 'Контрольный результат'], [[m['due'], m['owner'], m['result']] for m in plan['milestones']]), '',
               'Критический путь: F-13 → A-14/F-14 → A-15 → R-13/A-17 → F-15/R-05/R-06 → A-16/R-09/F-16/A-18/R-14 → R-10 → R-11 → F-17/R-12. Порядок внутри дня определяется подробными сроками и явными dependencies; это схема передач, а не дополнительная циклическая зависимость. При дефиците времени сначала сокращаются P1/P2, затем корректируется внутренний freeze; недостоверный ready-инсайт не является допустимым упрощением.', '',
               '## Контракт на согласование, не уже реализованный API', '', table_md(['Часть', 'Предложение F-13/A-15'], plan['contract_outline']), '', '**Общий текст notice_v1:** ' + NOTICE, '',
               'Фёдор владеет AI schema/смыслом вывода, Алексей — wire OpenAPI/DTO/хранением/доступами, Роман — одним generated TypeScript-контрактом и отображением. Значения disclaimer задаёт приложение; отсутствие предупреждения в модельном ответе не позволяет скрыть его в UI.', '',
               '## Какие уточнения нельзя принимать за проверенные факты', '', table_md(['Вопрос', 'Что требует проверки', 'Безопасное решение до уточнения', 'Владелец'], plan['data_questions']), '',
               'Журнал уточнений содержит source/date/confirmed-by/status/решение и влияние на версии. Нельзя молча подменять неоднозначное поле на более удобную интерпретацию. Неизвестный показатель не означает нулевой; групповой оборот не равен выручке/консолидированной отчётности, а платёжная связь не доказывает товарный поток.', '',
               '## Покрытие официальных критериев', '', 'Нумерация 01–12 сверена со страницами 9–10 исходного кейса, а не с порядком блоков при извлечении текста PDF.', '', table_md(['№', 'Критерий', 'Задачи'], plan['criteria']), '',
               '## Общая приёмка S01–S14', '', table_md(['ID', 'Сценарий', 'Ожидание', 'Владелец'], plan['scenarios']), '',
               '## Метрики без приписывания нормативов организаторам', '', table_md(['Метрика', 'Расчёт и границы', 'Данные/владелец'], plan['metrics']), '',
               plan['release_gate'], '',
               'Benchmark: не менее 6 компаний, 3 отраслей, 2 должностей на общей компании и 10 событий на контекст. Роль/должность не является enum прав. На демонстрации достаточно двух контрастных компаний и новой новости; покрытие всего CSV подтверждается отдельным техническим отчётом. Не требуется заранее генерировать LLM-инсайты для всех компаний × всех событий.', '',
               '## Основания и ограничения анализа', '']
    result += [f'- **{key}:** {value}' for key, value in plan['sources'].items()]
    result += ['', f'Сохранённый вход анализа: `output/planning/source/webinar-analysis-2026-10-21.txt`, SHA256 `{plan["analysis_sha256"]}`.', '',
               'Разрешённые LLM сверяются с приложением 3 и доступом команды; названия из расшифровки не являются allowlist. Закрытый Alfa Research-коннектор, новая CRM, смена агентского фреймворка/БД и отдельное мобильное приложение не входят в P0. Текущая база уже модульна; эти изменения локализуются в существующих features/services/AI schemas.', '']
    return '\n'.join(result)


def write_markdown(plan):
    folder = REPO / 'docs/planning'
    for person in plan['people']:
        (folder / f'{person}.md').write_text(person_md(plan, person).rstrip() + '\n', encoding='utf-8')
    (folder / 'webinar-review.md').write_text(review_md(plan).rstrip() + '\n', encoding='utf-8')
    stats = validate(plan)
    lines = ['# Задачи команды — редакция после вебинара', '', 'Редакция 21.10.2026 · МСК · внутренний план до сдачи 26.10. Точное официальное время проверяется в R-12.', '',
             f'База: `main {plan["baseline_sha"]}`. Единственный каталог — [plan.json](docs/planning/plan.json); обоснование/неоднозначности/критерии — [webinar-review.md](docs/planning/webinar-review.md).', '', plan['closure_note'], '',
             f'**Итог:** закрыто {stats["done"]}; изменённых нерешённых задач {stats["revised"]}; новых задач {stats["new"]}. Приоритеты P0/P1/P2 и сроки ниже — решения команды, не новые нормативы организаторов.', '',
             table_md(['Кто', 'Закрыто', 'Активно', 'Из них новых', 'Чистое время, ч'], [[person['name'], sum(t['status']=='done' for t in plan['tasks'][key]), len(active(plan,key)), sum(t['status']=='new' for t in plan['tasks'][key]), sum(t.get('estimate_hours',0) for t in active(plan,key))] for key,person in plan['people'].items()]), '',
             'Путь пользователя: Альфа-Бизнес → готовый персональный вывод → причины/источники/банк → уточнение → demo-действие/feedback. Неизвестное не заменяется фиктивными данными. Статус новой задачи не означает уже работающий функционал.', '',
             '## Контрольные точки', '', table_md(['Срок МСК', 'Кто', 'Результат'], [[m['due'], m['owner'], m['result']] for m in plan['milestones']]), '']
    for person in plan['people']:
        # The exact same records form the role PDFs and full task descriptions.
        lines += [person_md(plan, person).replace('# ', '## ', 1), '']
    lines += ['## Правила завершения и сдачи', '', 'Задача закрывается после коммита, PR, указанной приёмки и интеграции в общую ветку. Новые договорённости о schema/data/policy фиксируются версиями, не устными сообщениями. Повторная проверка релиза ссылается на фактический SHA, а не исторический PASS другого состояния.', '',
              'S01–S14, определения метрик, спорные поля CSV и покрытие 12 официальных критериев находятся в [обосновании пересмотра](docs/planning/webinar-review.md). Полная детализация исходных закрытых задач сохранена в plan.json и архиве от 19.10.2026.', '']
    content = '\n'.join(lines)
    (REPO / 'TASKS.md').write_text(content, encoding='utf-8')
    # This export lives outside the Git repository, so links point back to it.
    (OUT / 'TASKS.md').write_text(content.replace('](docs/', '](../../GOAT_hack/docs/'), encoding='utf-8')


def esc(value):
    return html.escape(str(value))


def paragraph(value, cls=''):
    return f'<p class="{cls}">{esc(value)}</p>'


def table(headings, rows):
    return '<table><thead><tr>' + ''.join(f'<th>{esc(x)}</th>' for x in headings) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{esc(x)}</td>' for x in row) + '</tr>' for row in rows) + '</tbody></table>'


def ul(values):
    return '<ul>' + ''.join(f'<li>{esc(value)}</li>' for value in values) + '</ul>'


def page(title, content, label='План после вебинара'):
    return {'title': title, 'content': content, 'label': label}


def task_page(task):
    content = paragraph(f'{task["code"]} · {LABELS[task["status"]]} · {task["priority"]}', 'eyebrow')
    content += paragraph('Срок: ' + task['due'] + ' МСК', 'deadline')
    if task.get('original_due'):
        content += paragraph('Прежний срок: ' + task['original_due'] + '. Перенесён в актуальный внутренний график.', 'small')
    if task.get('extends'):
        content += paragraph('Продолжение выполненных: ' + ', '.join(task['extends']) + '.', 'small')
    content += paragraph('Зависимости: ' + (', '.join(task['dependencies']) or 'готовые модули, новых блокеров нет') + '.')
    content += '<h2>Что сделать</h2>' + ul(task['steps'])
    content += '<h2>Результат в коммите</h2>' + ul(task['deliverables'])
    content += '<h2>Как принимаем</h2>' + ul(task['checks'])
    content += paragraph('Коммит: ' + task['commit'], 'small')
    content += paragraph('Основания: ' + ', '.join(task['sources']) + f'. Оценка чистого времени: {task["estimate_hours"]} ч.', 'small')
    return page(task['title'], content, task['code'])


def person_pages(plan, person):
    info = plan['people'][person]
    pending = active(plan, person)
    done = [t for t in plan['tasks'][person] if t['status'] == 'done']
    intro = paragraph(info['scope'] + '.', 'lead') + paragraph(info['reviewer'])
    intro += paragraph(f'Закрыто {len(done)} исходных реализаций; актуальных задач {len(pending)}. Оценка чистого времени {sum(t["estimate_hours"] for t in pending)} ч. Все даты — октябрь 2026, МСК; сроки внутренние, официальный дедлайн уточняется отдельно.', 'callout')
    intro += table(['ID', 'Срок МСК', 'Приоритет', 'Результат'], [(t['code'], t['due'], t['priority'], t['title']) for t in pending])
    intro += paragraph('Порядок таблицы — рабочий график. P0 сначала; расширенная админка/мобильная разработка/новые фреймворки не вытесняют достоверность инсайта. Детальные зависимости и приёмка — на следующих страницах.', 'small')
    history = paragraph(plan['closure_note'], 'callout') + table(['ID', 'Выполненная исходная задача'], [(t['code'], t['title']) for t in done])
    history += '<h2>Подтверждение</h2>' + ul(sorted({e for t in done for e in t['evidence']}))
    history += paragraph('История исходной постановки не переписана. До 26.10 повторная проверка выполняется уже на финальном SHA в A-17/A-18/F-17/R-10–R-12. Полная прежняя редакция сохранена в output/planning/archive/2026-10-19.', 'small')
    return [page(info['name'] + ' — актуальные задачи', intro), page('Что уже выполнено', history)] + [task_page(t) for t in pending]


def overview_pages(plan):
    stats = validate(plan)
    summary = paragraph('Ценность — готовый бизнес-инсайт, а не новость с кнопкой AI.', 'lead') + paragraph('Альфа-Бизнес → персональный вывод → проверяемые причины → уточнение → следующее действие.', 'callout')
    summary += table(['Участник', 'Закрыто', 'Изменено', 'Добавлено'], [['Роман', 'R-00–R-04', 'R-05–R-12', 'R-13–R-14'], ['Алексей', 'A-01–A-13', '—', 'A-14–A-18'], ['Фёдор', 'F-01–F-12', '—', 'F-13–F-17']])
    summary += paragraph(f'Сохранено закрытых реализаций: {stats["done"]}; изменено задач: {stats["revised"]}; добавлено: {stats["new"]}. Активных задач: {stats["revised"] + stats["new"]}. Это новый план реализации, а не отчёт о готовности v2.', 'deadline')
    summary += ul(plan['decisions'][:5])
    summary += paragraph('Аудит выполнен по коду/истории и существующим артефактам, не по одному PDF. Backend уже импортировал 1 380 585 платежных строк; AI имеет S1–S8/OCR/RAG приёмку, но её ограничения требуют продолжений A-14/F-15.', 'small')
    owners = ''
    for person, info in plan['people'].items():
        owners += '<h2>' + esc(info['name']) + '</h2>'
        owners += table(['ID', 'Что добавляется/меняется'], [[t['code'] + ' / ' + t['priority'], t['title']] for t in active(plan, person)])
    schedule = table(['Срок МСК', 'Кто', 'Результат'], [[m['due'], m['owner'], m['result']] for m in plan['milestones']])
    schedule += paragraph('Критический путь: контракт/семантика → влияние/API → лента/чат → действия и измерения → общая приёмка → freeze → сдача. Зависимости ацикличны, сроки передач проверены генератором.', 'callout')
    schedule += paragraph('Ранний сквозной smoke — 23.10 20:00; S01–S14 — 24.10 16:00; внутренний freeze — 20:00. Неисправленный P0 не называется готовым MVP. При риске срока сокращаются P1/P2 и пересматривается внутренний график.', 'small')
    contract = table(['Часть', 'Предложение v2'], plan['contract_outline']) + paragraph('Владельцы: AI schema — Фёдор; OpenAPI/DTO/хранение — Алексей; generated types/UI — Роман. Один HTTP-клиент, одна очередь, существующая модульная архитектура.', 'callout')
    contract += '<h2>Обязательный notice_v1</h2>' + paragraph(NOTICE) + paragraph('Текст задаёт приложение. Предупреждение не оправдывает неподтверждённые факты. Чтение старых v1 результатов имеет безопасный fallback; новый schema/semantics/prompt меняет ключ кеша.', 'small')
    questions = table(['ID / предмет', 'Правило до подтверждения', 'Владелец'], [[r[0] + ': ' + r[1], r[2], r[3]] for r in plan['data_questions']])
    questions += paragraph('Источник кейса выше вторичного анализа. Страны ФТС не задают направление торговли; платёж — не поставка; группа — не доля собственности; self-платежи не равны внешнему обороту. Raw/quality/provenance сохраняются.', 'small')
    metrics = table(['Метрика', 'Формула / ограничение', 'Откуда'], plan['metrics']) + paragraph('Benchmark: ≥6 компаний / ≥3 отраслей / ≥2 должностей на общей компании / ≥10 событий на контекст. Синтетический и настоящий трафик раздельны; пустые знаменатели — N/A.', 'callout')
    metrics += paragraph('Цели/пороги назначает команда до замера, это не норматив организаторов. Ни engagement demo-сеанса, ни запись demo-обращения не доказывают реальный банковский эффект.', 'small')
    sources = ul([f'{key}: {value}' for key, value in plan['sources'].items()])
    sources += paragraph('Baseline main: ' + plan['baseline_sha'], 'small') + paragraph('SHA256 анализа: ' + plan['analysis_sha256'], 'small')
    sources += '<h2>Что не усложняем</h2>' + paragraph('Регистрация/членства/auth сохраняются. Демонстрационный вход — подготовленный пользователь с подтверждёнными компаниями. Расширенная админка — P2; операторский минимум — P1. Базовая адаптивность остаётся, отдельного mobile app нет.')
    sources += paragraph('Не добавляем закрытый Alfa Research-коннектор, реальную CRM, новую БД или смену агентского фреймворка без нужды. Собственная многошаговая агентная логика, allowlist моделей, серверные права и бюджет обязательны по исходному кейсу.')
    sources += '<h2>Выходные файлы и архив</h2>' + paragraph('GOAT_hack/TASKS.md и docs/planning/plan.json — полный каталог; roman.md/alexey.md/fedor.md — персональные списки; webinar-review.md — решения и вопросы. Четыре актуальных PDF — output/planning. Старая редакция — archive/2026-10-19.')
    sources += paragraph('Новый полный тестовый прогон приложения при пересмотре документов не запускался. Исторические PASS не подтверждают ещё не реализованный v2.', 'small')
    return [page('От событий к решениям', summary), page('Задачи всех участников', owners), page('Передачи и сроки', schedule),
            page('Контракт бизнес-инсайта', contract), page('Семантика: не домысливать', questions),
            page('12 критериев исходного кейса', table(['№', 'Критерий', 'Задачи'], plan['criteria']) + paragraph('Номера сверены с расположением блоков на стр. 9–10 Кейс.pdf. Приоритет исходного кейса выше пересказа вебинара.', 'small')),
            page('Приёмка S01–S14', table(['ID', 'Сценарий', 'Ожидание / владелец'], [[r[0], r[1], r[2] + ' / ' + r[3]] for r in plan['scenarios']]) + paragraph(plan['release_gate'], 'small')),
            page('Измеряем продуктовую ценность', metrics), page('Основания и границы объёма', sources)]


CSS = '''
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; color: #17212f; font-family: Arial, sans-serif; }
.sheet { width: 210mm; height: 297mm; padding: 14mm 14mm 15mm; position: relative; break-after: page; }
.sheet:last-child { break-after: auto; }
header { display: flex; justify-content: space-between; gap: 6mm; border-top: 3px solid #ed2024; padding-top: 3mm; margin-bottom: 4mm; font-size: 8pt; color: #67717f; }
header b { color: #ed2024; }
.body { height: 249mm; font-size: 9.6pt; line-height: 1.35; }
h1 { font-size: 23pt; line-height: 1.13; margin: 0 0 4mm; letter-spacing: -.45px; }
h2 { font-size: 12pt; line-height: 1.2; margin: 3.5mm 0 1.6mm; }
p { margin: 2mm 0; overflow-wrap: anywhere; }
ul { padding-left: 5mm; margin: 2mm 0 3mm; }
li { margin-bottom: 2.1mm; overflow-wrap: anywhere; }
.lead { font-size: 12pt; line-height: 1.45; }
.eyebrow { color: #b52a20; font-size: 9pt; font-weight: bold; }
.deadline { font-weight: bold; }
.small { font-size: 8.3pt; color: #596678; }
.callout { background: #f3f5f8; border-left: 3px solid #ed2024; padding: 3mm; margin: 3mm 0; }
table { width: 100%; table-layout: auto; border-collapse: collapse; font-size: 8.4pt; line-height: 1.3; margin: 3mm 0; }
th { text-align: left; background: #eef1f5; }
td, th { border-bottom: 1px solid #dfe4eb; vertical-align: top; padding: 2mm 2.1mm; overflow-wrap: anywhere; }
td:first-child { min-width: 10mm; }
td:last-child { min-width: 19mm; }
footer { position: absolute; bottom: 8mm; left: 14mm; right: 14mm; border-top: 1px solid #dfe4eb; padding-top: 2mm; display: flex; justify-content: space-between; color: #67717f; font-size: 8pt; }
'''


def html_document(pages, title):
    sheets = []
    for index, item in enumerate(pages, 1):
        sheets.append(f'<article class="sheet"><header><b>GOAT_hack</b><span>{esc(item["label"])}</span><span>Редакция 21.10.2026 · МСК</span></header><main class="body"><h1>{esc(item["title"])}</h1>{item["content"]}</main><footer><span>{esc(title)} · версии 22–26.10</span><span>{index} / {len(pages)}</span></footer></article>')
    return '<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>' + esc(title) + '</title><style>' + CSS + '</style></head><body>' + ''.join(sheets) + '</body></html>'


def render(plan, with_pdf):
    source = OUT / 'source'
    source.mkdir(parents=True, exist_ok=True)
    write_markdown(plan)
    (source / 'tasks.json').write_text(json.dumps(plan['tasks'], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (source / 'plan.json').write_bytes(CATALOGUE.read_bytes())
    (source / 'task_catalog.py').write_text('''"""Compatibility export; source of truth is GOAT_hack/docs/planning/plan.json."""
import json
from pathlib import Path
PLAN = json.loads((Path(__file__).resolve().parents[3] / 'GOAT_hack/docs/planning/plan.json').read_text(encoding='utf-8'))
PEOPLE = PLAN['people']
TASKS = PLAN['tasks']
HTTP_CONTRACT = PLAN['contract_outline']
''', encoding='utf-8')
    (source / 'build_documents.py').write_text('''"""Use the versioned renderer, not the archived original generator."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parents[3] / 'GOAT_hack/scripts/render_planning.py'), run_name='__main__')
''', encoding='utf-8')
    documents = [('00-system-overview', 'Система и новый план', overview_pages(plan))]
    documents += [(f'0{index}-{person}-tasks', plan['people'][person]['name'] + ' — персональный план', person_pages(plan, person)) for index, person in enumerate(plan['people'], 1)]
    for name, title, pages in documents:
        (source / f'{name}.html').write_text(html_document(pages, title), encoding='utf-8')
    if not with_pdf:
        return []
    import fitz
    from playwright.sync_api import sync_playwright
    report = []
    preview = OUT / 'preview'
    preview.mkdir(exist_ok=True)
    with sync_playwright() as engine:
        browser = engine.chromium.launch(channel='msedge', headless=True)
        tab = browser.new_page()
        for name, title, pages in documents:
            tab.set_content((source / f'{name}.html').read_text(encoding='utf-8'), wait_until='load')
            tab.emulate_media(media='print')
            tab.evaluate('document.fonts.ready')
            overflow = tab.evaluate('''() => [...document.querySelectorAll('.body')].map((el,i)=>({page:i+1,overflow:el.scrollHeight-el.clientHeight,bottom:el.getBoundingClientRect().bottom,lastBottom:el.lastElementChild.getBoundingClientRect().bottom})).filter(x=>x.overflow>2||x.lastBottom>x.bottom+2)''')
            if overflow:
                raise ValueError(f'PDF layout overflow {name}: {overflow}')
            dest = OUT / f'{name}.pdf'
            tab.pdf(path=str(dest), format='A4', print_background=True, prefer_css_page_size=True)
            with fitz.open(dest) as doc:
                assert len(doc) == len(pages), f'Wrong PDF page count: {name}'
                assert all(len(p.get_text().strip()) > 180 for p in doc), f'Empty PDF page: {name}'
                for index, pdf_page in enumerate(doc):
                    if index == 0 or index == 2 or name == '00-system-overview' and index in {4, 6}:
                        pdf_page.get_pixmap(matrix=fitz.Matrix(1.15, 1.15)).save(preview / f'{name}-v2-p{index+1:02d}.png')
                record = {'file': dest.name, 'pages': len(doc), 'bytes': dest.stat().st_size, 'text_chars': sum(len(p.get_text()) for p in doc), 'result': 'PASS', 'overflow': []}
                report.append(record)
                print(json.dumps(record, ensure_ascii=False), flush=True)
        browser.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--no-pdf', action='store_true')
    args = parser.parse_args()
    plan = json.loads(CATALOGUE.read_text(encoding='utf-8'))
    validation = validate(plan)
    if args.check:
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return
    OUT.mkdir(parents=True, exist_ok=True)
    report = render(plan, not args.no_pdf)
    (OUT / 'generation-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (OUT / 'verification-report.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
