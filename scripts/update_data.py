"""Оновлює data/alerts.json: тривоги м. Київ з офіційних джерел КМДА.

1. Відкритий набір КМДА «Статистика повітряних тривог на території Києва» (data.gov.ua, CC BY 4.0):
   час початку й відбою + рівень загрози. Оновлюється щопонеділка.
2. Журнал тривог міського сервісу «Київ Цифровий» (kyiv.digital): час початку й відбою, без рівня.
   Ним доповнюємо дні після останнього оновлення набору КМДА.
3. Офіційний Telegram-канал КМВА (t.me/VA_Kyiv): повідомлення «Червоний/Жовтий рівень небезпеки».
   З нього беремо рівень для тривог з журналу «Київ Цифровий» — щоб рівні були щодня, а не лише після
   понеділкового оновлення КМДА. Правило — як у наборі КМДА: якщо рівень під час тривоги змінювався,
   тривозі присвоюється останній оголошений рівень (перевірено на жовтні 2026: збіг 166 з 168).
Запускається GitHub Actions щогодини. Нічого вручну робити не треба.
"""
import datetime as dt, json, os, re, sys, urllib.request

DATASET_ID = "48330a76-8539-4079-8d83-42fa9ba6537c"
JSON_URL = ("https://data.gov.ua/dataset/83eda433-b4d9-47ac-89a0-5868dd4d5ce6/resource/"
            "08559e6a-863f-4d9b-86c1-d23e8b8b4630/download/airalerts.json")
KD_URL = "https://kyiv.digital/storage/air-alert/stats.html"
KMVA_URL = "https://t.me/s/VA_Kyiv"
SINCE = "2026-09-01"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "alerts.json")
UA = {"User-Agent": "Mozilla/5.0 (tabel-tryvog data updater)"}
KYIV = dt.timezone(dt.timedelta(hours=2))  # уточнюється нижче через zoneinfo


def now_kyiv():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Europe/Kyiv")).replace(tzinfo=None)
    except Exception:
        return dt.datetime.utcnow() + dt.timedelta(hours=2)


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def official():
    """Набір КМДА. Повертає список (start, end, level) у місцевому часі."""
    urls = [JSON_URL]
    try:
        meta = json.loads(get("https://data.gov.ua/api/3/action/package_show?id=" + DATASET_ID))
        for res in meta["result"]["resources"]:
            if res.get("format", "").upper() == "JSON" and res.get("url"):
                urls.insert(0, res["url"])
    except Exception as e:
        print("package_show недоступний:", e)
    last_err = None
    for u in urls:
        try:
            data = json.loads(get(u).decode("utf-8-sig"))
            break
        except Exception as e:
            last_err = e
    else:
        raise RuntimeError("набір КМДА недоступний: %s" % last_err)
    if isinstance(data, dict):
        data = next(v for v in data.values() if isinstance(v, list))
    out = []
    for x in data:
        s = (x.get("dateTimeStart") or "")[:16]
        if not s or s < SINCE:
            continue
        e = (x.get("dateTimeEnd") or "")[:16] or None
        if e in ("null", "None"):
            e = None
        lv = x.get("level") or ""
        lv = "r" if "Черв" in lv else ("y" if "Жовт" in lv else "")
        out.append([s, e, lv])
    return out


def kyiv_digital():
    """Журнал «Київ Цифровий». Повертає список (start, end, '')."""
    html = get(KD_URL).decode("utf-8", "replace")
    text = re.sub(r"<[^>]+>", " ", html)
    pat = re.compile(r"(\d{2}):(\d{2})\s+(\d{2})\.(\d{2})\.(\d{2})\s*\S*\s*(Повітряна тривога|Відбій)")
    ev = []
    for m in pat.finditer(text):
        hh, mi, d, mo, y, kind = m.groups()
        t = dt.datetime(2000 + int(y), int(mo), int(d), int(hh), int(mi))
        ev.append((t, 0 if kind.startswith("Відбій") else 1))
    ev.sort()
    out, start = [], None
    for t, k in ev:
        if k == 1:
            if start is not None:  # дві тривоги поспіль без відбою — закриваємо попередню
                out.append([start.strftime("%Y-%m-%dT%H:%M"), t.strftime("%Y-%m-%dT%H:%M"), ""])
            start = t
        elif start is not None:
            out.append([start.strftime("%Y-%m-%dT%H:%M"), t.strftime("%Y-%m-%dT%H:%M"), ""])
            start = None
    if start is not None:
        out.append([start.strftime("%Y-%m-%dT%H:%M"), None, ""])
    return [a for a in out if a[0] >= SINCE]


def kmva_levels(since):
    """Повідомлення каналу КМВА з моменту since: список (local 'YYYY-MM-DDTHH:MM', 'r'|'y'|'end')."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Kyiv")
    out, before = [], None
    for _ in range(60):
        html_ = get(KMVA_URL + ("?before=%d" % before if before else ""), timeout=30).decode("utf-8", "replace")
        ids, oldest = [], None
        for blk in html_.split('class="tgme_widget_message_wrap')[1:]:
            m = re.search(r'data-post="[^/"]+/(\d+)"', blk)
            t = re.search(r'<time datetime="([^"]+)"', blk)
            x = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', blk, re.S)
            if not (m and t):
                continue
            ids.append(int(m.group(1)))
            loc = dt.datetime.fromisoformat(t.group(1)).astimezone(tz).strftime("%Y-%m-%dT%H:%M")
            oldest = loc if oldest is None or loc < oldest else oldest
            if not x:
                continue
            txt = re.sub(r"<[^>]+>", " ", x.group(1)).lower()
            if "відбій" in txt and "тривог" in txt:
                out.append((loc, "end"))
                continue
            if "рівень небезпеки" not in txt:
                continue
            if "червоний рівень" in txt:
                out.append((loc, "r"))
            elif "жовтий рівень" in txt:
                out.append((loc, "y"))
        if not ids or (oldest and oldest < since):
            break
        before = min(ids)
    return sorted(set(out))


def add_levels(alerts, levels):
    """Тривогам без рівня присвоює останній рівень, оголошений КМВА від початку тривоги (−3 хв) до відбою КМВА."""
    n = 0
    for a in alerts:
        if a[2]:
            continue
        lo = (dt.datetime.strptime(a[0], "%Y-%m-%dT%H:%M") - dt.timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M")
        hi = a[1] or "9999"
        seq = []
        for t, lv in levels:
            if t < lo or t >= hi:
                continue
            if lv == "end":
                if t > a[0]:   # відбій КМВА після початку цієї тривоги — далі вже наступна тривога
                    break
                continue
            seq.append(lv)
        if seq:
            a[2] = seq[-1]
            n += 1
    return n


def main():
    off, kd, notes = [], [], []
    try:
        off = official()
    except Exception as e:
        notes.append("КМДА data.gov.ua: " + str(e))
    try:
        kd = kyiv_digital()
    except Exception as e:
        notes.append("kyiv.digital: " + str(e))
    old = {}
    if os.path.exists(OUT):
        old = json.load(open(OUT, encoding="utf-8"))
    if not off and not kd:
        print("Обидва джерела недоступні, дані не змінено:", notes)
        return 0
    if not off:  # набір КМДА тимчасово недоступний — беремо офіційну частину з попереднього файлу
        off = [a for a in old.get("alerts", []) if a[3:4] == ["kmda"]]
        off = [a[:3] for a in off]
    official_until = max((a[1] or a[0]) for a in off) if off else SINCE
    merged = [a + ["kmda"] for a in off]
    fresh = [a for a in kd if a[0] > official_until]  # «Київ Цифровий» — лише після останнього запису КМДА
    if fresh:
        try:
            lv = kmva_levels(min(a[0] for a in fresh)[:10])
            print("КМВА: рівень додано", add_levels(fresh, lv), "з", len(fresh), "тривог")
        except Exception as e:
            notes.append("КМВА t.me: " + str(e))
    for a in fresh:
        merged.append(a + ["kd"])
    merged.sort(key=lambda a: a[0])
    result = {
        "updated": now_kyiv().strftime("%Y-%m-%dT%H:%M"),
        "official_until": official_until,
        "sources": {
            "kmda": "КМДА, набір даних «Статистика повітряних тривог на території Києва», data.gov.ua, CC BY 4.0",
            "kd": "Журнал повітряних тривог міського сервісу «Київ Цифровий» (kyiv.digital)",
            "kmva": "Офіційний Telegram-канал Київської міської військової адміністрації (t.me/VA_Kyiv) — рівень загрози",
        },
        "notes": notes,
        "alerts": merged,
    }
    # Навіть без нових тривог оновлюємо файл щонайменше раз на 6 годин:
    # за полем updated сайт і розсилка бачать, що дані за минулі дні вже повні.
    stale = True
    if old.get("updated"):
        prev = dt.datetime.strptime(old["updated"], "%Y-%m-%dT%H:%M")
        stale = now_kyiv().replace(tzinfo=None) - prev >= dt.timedelta(hours=6)
    if old.get("alerts") == merged and old.get("official_until") == official_until and not stale:
        print("Без змін")
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    print("Оновлено:", len(merged), "тривог; офіційні дані до", official_until, notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
