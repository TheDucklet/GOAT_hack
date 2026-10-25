import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

AS_OF = "2026-10-25T00:00:00+03:00"
SEED = 20261025
FEED = "https://www.cbr.ru/rss/eventrss"
REAL = (
    ("ev2-cbr-money-credit-2026-09-24", "macro", "https://www.cbr.ru/press/event/?id=32869"),
    ("ev2-cbr-nonresident-transfers-2026-09-24", "regulatory", "https://www.cbr.ru/press/event/?id=32871"),
    ("ev2-cbr-digital-depositories-2026-10-06", "neutral", "https://www.cbr.ru/press/event/?id=32894"),
)
SYNTHETIC = (
    {
        "id": "ev2-syn-marketplace-commission",
        "category": "sector_retail",
        "title": "Правительство предложило ограничить комиссии маркетплейсов для розничных продавцов",
        "published_at": "2026-10-12T10:00:00+03:00",
        "text": (
            "Минэкономразвития опубликовало проект постановления, который ограничивает комиссию маркетплейсов для продавцов "
            "непродовольственных товаров 15% от стоимости заказа с 1 января 2027 года. По оценке ведомства, действующая средняя "
            "комиссия составляет 19%. Ассоциации продавцов ожидают, что мера увеличит их валовую выручку на 2-3%, а крупные "
            "платформы заявили о возможном росте тарифов на логистику и рекламу. Публичное обсуждение проекта продлится до "
            "1 ноября 2026 года."
        ),
    },
    {
        "id": "ev2-syn-heavy-truck-toll",
        "category": "sector_transport",
        "title": "Минтранс вводит плату за проезд тяжёлых грузовиков по федеральным трассам",
        "published_at": "2026-10-14T11:00:00+03:00",
        "text": (
            "Министерство транспорта сообщило, что с 1 января 2027 года на федеральных трассах будет введена плата за проезд "
            "грузовиков с разрешённой массой более 12 тонн в размере 2,1 рубля за километр. По расчётам министерства, поступления "
            "составят 31 млрд рублей в год и будут направлены на ремонт дорог. Перевозчики просят освободить от платы "
            "автомобили, зарегистрированные до 2020 года, и ввести переходный период до 1 июля 2027 года."
        ),
    },
    {
        "id": "ev2-syn-city-park",
        "category": "neutral",
        "title": "В городе открылся новый парк",
        "published_at": "2026-10-20T09:00:00+03:00",
        "text": (
            "В городе открылся новый парк площадью 18 гектаров с велодорожками, детскими площадками и прудом. Администрация "
            "сообщила, что на благоустройство потрачено 640 млн рублей из городского бюджета. Парк рассчитан на 12 тысяч "
            "посетителей в день, второй этап строительства планируется в следующем году."
        ),
    },
)
PRINT_BLOCK = re.compile(r'<div class="print-button-wrap"')


def clean(markup: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", markup)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def fetch_page(url: str) -> dict:
    response = httpx.get(url, timeout=40, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
    response.raise_for_status()
    page = response.text
    title = clean(re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S).group(1))
    lead = re.search(r'<div class="lead-text">(.*?)</div>', page, re.S)
    body = re.search(r'<div class="landing-text">(.*?)</div>\s*<!--noindex-->', page, re.S) or re.search(
        r'<div class="landing-text">(.*?)</div>', page, re.S
    )
    parts = [clean(item.group(1)) for item in (lead, body) if item]
    text = re.sub(r"\s*Фото на превью:.*$", "", " ".join(part for part in parts if part))
    return {"title": title, "text": text}


def feed_times() -> dict[str, str]:
    root = ET.fromstring(httpx.get(FEED, timeout=40, headers={"User-Agent": "Mozilla/5.0"}).content)
    return {
        item.findtext("link"): parsedate_to_datetime(item.findtext("pubDate")).isoformat()
        for item in root.findall(".//item")
    }


def build(directory: Path) -> dict:
    times = feed_times()
    events = []
    for event_id, category, url in REAL:
        page = fetch_page(url)
        published = datetime.fromisoformat(times[url])
        events.append(
            {
                "id": event_id,
                "source": "real_public_cbr",
                "category": category,
                "used_in_tuning": False,
                "text_kind": "full_text",
                "note": "Полный текст страницы Банка России без пересказа.",
                "title": page["title"],
                "published_at": published.isoformat(),
                "url": url,
                "text": page["text"],
                "sha256": hashlib.sha256(page["text"].encode("utf-8")).hexdigest(),
            }
        )
    for item in SYNTHETIC:
        events.append(
            {
                "id": item["id"],
                "source": "synthetic",
                "category": item["category"],
                "used_in_tuning": False,
                "text_kind": "synthetic",
                "note": f"Синтетическая новость, числа вымышлены, seed {SEED}.",
                "title": item["title"],
                "published_at": item["published_at"],
                "url": None,
                "text": item["text"],
                "sha256": hashlib.sha256(item["text"].encode("utf-8")).hexdigest(),
            }
        )
    assert all(item["published_at"] <= AS_OF for item in events)
    value = {"as_of": AS_OF, "seed": SEED, "events": events}
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "events.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return value
