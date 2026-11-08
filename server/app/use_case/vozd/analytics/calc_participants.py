"""Калькуляторы по профилям участников (прямые поля VK API). Закрытые профили — «нет данных», без оценки."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from app.use_case.vozd.analytics import util as u
from app.use_case.vozd.analytics.context import AnalyticsContext
from app.use_case.vozd.analytics.registry import InsufficientData, MetricUnavailable, calculator

_DEFAULT_PHOTO_MARKERS = ("camera_", "deactivated_", "/images/camera")


async def _profiles(ctx: AnalyticsContext):
    """(все участники VK, открытые профили с данными)."""
    users = [usr for (pl, _), usr in (await ctx.users()).items() if pl == "vk"]
    ok = [usr for usr in users if usr.profile_status == "ok" and usr.profile]
    return users, ok


def _coverage(users, ok) -> dict:
    statuses = Counter(usr.profile_status for usr in users)
    return {
        "participants_vk": len(users),
        "profiles_open": len(ok),
        "profiles_closed": statuses.get("closed", 0),
        "profiles_deleted_or_banned": statuses.get("deleted", 0) + statuses.get("banned", 0),
        "profiles_not_collected": statuses.get("pending", 0),
        "coverage": u.share(len(ok), len(users)),
        "note": "оценка только по открытым профилям VK; для закрытых и Telegram данных нет",
    }


@calculator("II.1")
async def sex(ctx: AnalyticsContext):
    users, ok = await _profiles(ctx)
    if not ok:
        raise InsufficientData("нет собранных открытых профилей")
    c = Counter({1: 0, 2: 0, 0: 0})
    for usr in ok:
        c[usr.profile.get("sex") if usr.profile.get("sex") in (1, 2) else 0] += 1
    known = c[1] + c[2]
    return {
        "female": c[1],
        "male": c[2],
        "unspecified": c[0],
        "female_share_of_known": u.share(c[1], known),
        "male_share_of_known": u.share(c[2], known),
        **_coverage(users, ok),
    }


def _age(bdate: str, today: datetime) -> int | None:
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", bdate or "")
    if not m:
        return None
    d, mo, y = map(int, m.groups())
    try:
        age = today.year - y - ((today.month, today.day) < (mo, d))
    except ValueError:
        return None
    return age if 5 <= age <= 100 else None


@calculator("II.2")
async def age(ctx: AnalyticsContext):
    users, ok = await _profiles(ctx)
    today = datetime.now(tz=timezone.utc)
    ages = [a for a in (_age(usr.profile.get("bdate", ""), today) for usr in ok) if a is not None]
    if not ages:
        raise InsufficientData("ни у кого из собранных профилей не указан полный год рождения")
    bands = [("<18", 0, 17), ("18-24", 18, 24), ("25-34", 25, 34), ("35-44", 35, 44), ("45-54", 45, 54), ("55+", 55, 200)]
    ages.sort()
    return {
        "with_known_age": len(ages),
        "median": ages[len(ages) // 2],
        "mean": u.mean(ages),
        "bands": [{"band": n, "count": sum(1 for a in ages if lo <= a <= hi), "share": u.share(sum(1 for a in ages if lo <= a <= hi), len(ages))} for n, lo, hi in bands],
        **_coverage(users, ok),
    }


@calculator("II.3")
async def geography(ctx: AnalyticsContext):
    users, ok = await _profiles(ctx)
    cities: Counter = Counter()
    countries: Counter = Counter()
    for usr in ok:
        city = (usr.profile.get("city") or {}).get("title")
        country = (usr.profile.get("country") or {}).get("title")
        if city:
            cities[city] += 1
        if country:
            countries[country] += 1
    if not (cities or countries):
        raise InsufficientData("город/страна не указаны в собранных профилях")
    return {
        "with_city": sum(cities.values()),
        "top_cities": u.top(cities, 25, "city"),
        "top_countries": u.top(countries, 15, "country"),
        **_coverage(users, ok),
    }


@calculator("II.4")
async def education(ctx: AnalyticsContext):
    users, ok = await _profiles(ctx)
    if not ok:
        raise InsufficientData("нет собранных открытых профилей")
    occ: Counter = Counter()
    unis: Counter = Counter()
    for usr in ok:
        p = usr.profile
        t = (p.get("occupation") or {}).get("type")
        if t:
            occ[t] += 1
        for un in p.get("universities") or []:
            if isinstance(un, dict) and un.get("name"):
                unis[un["name"]] += 1
    return {
        "occupation_types": u.top(occ, 5, "type"),
        "studying_now": occ.get("university", 0) + occ.get("school", 0),
        "with_university_info": sum(1 for usr in ok if usr.profile.get("universities")),
        "top_universities": u.top(unis, 15, "university"),
        **_coverage(users, ok),
        "note": "поле occupation (учёба/работа) есть у части профилей; список вузов — только в профилях, собранных после включения полей universities/schools/career",
    }


@calculator("II.5")
async def profession(ctx: AnalyticsContext):
    users, ok = await _profiles(ctx)
    if not ok:
        raise InsufficientData("нет собранных открытых профилей")
    employers: Counter = Counter()
    positions: Counter = Counter()
    working = 0
    for usr in ok:
        p = usr.profile
        occ = p.get("occupation") or {}
        if occ.get("type") == "work":
            working += 1
            if occ.get("name"):
                employers[occ["name"]] += 1
        for c in p.get("career") or []:
            if isinstance(c, dict):
                if c.get("company"):
                    employers[c["company"]] += 1
                if c.get("position"):
                    positions[c["position"].lower()] += 1
    return {
        "working": working,
        "top_employers": u.top(employers, 20, "employer"),
        "top_positions": u.top(positions, 20, "position"),
        **_coverage(users, ok),
    }


@calculator("I.18")
async def anonymity(ctx: AnalyticsContext):
    users, ok = await _profiles(ctx)
    if not users:
        raise InsufficientData("нет участников VK")
    no_photo = no_surname = 0
    for usr in ok:
        photo = str(usr.profile.get("photo_200") or "")
        if not photo or any(m in photo for m in _DEFAULT_PHOTO_MARKERS):
            no_photo += 1
        if not (usr.last_name or "").strip():
            no_surname += 1
    return {
        "open_profiles": len(ok),
        "default_or_no_photo": no_photo,
        "default_or_no_photo_share": u.share(no_photo, len(ok)),
        "without_surname": no_surname,
        "closed_profiles_share": u.share(sum(1 for usr in users if usr.profile_status == "closed"), len(users)),
        "method": "доля открытых профилей без аватара и доля закрытых профилей",
        **_coverage(users, ok),
    }


async def _split_old_new(ctx: AnalyticsContext):
    """Старожилы/новички по первому появлению в наших данных (дата вступления в группу недоступна)."""
    first = await ctx.count_first_seen()
    if not first:
        raise InsufficientData("нет комментариев")
    days = ctx.window.days or 30
    boundary = (ctx.window.date_to or datetime.now(tz=timezone.utc)).replace(microsecond=0)
    from datetime import timedelta

    boundary = boundary - timedelta(days=min(days, 365))
    new = {k for k, v in first.items() if v >= boundary}
    old = {k for k, v in first.items() if v < boundary}
    return boundary, new, old


@calculator("II.46", "II.47", "II.48")
async def oldtimers_newcomers(ctx: AnalyticsContext):
    await ctx.prepare()
    boundary, new, old = await _split_old_new(ctx)
    if not old:
        raise InsufficientData("все участники впервые появились в окне: сравнивать со старожилами не с чем (расширьте период сбора)")
    comments = [c for c in await ctx.human_comments() if c.published_at]
    by = {"newcomers": new, "oldtimers": old}
    stats = {}
    for name, ids in by.items():
        rows = [c for c in comments if (c.platform, c.from_id) in ids]
        stats[name] = {
            "participants": len(ids),
            "comments_in_window": len(rows),
            "comments_per_participant": u.r4(len(rows) / len(ids)) if ids else None,
            "avg_words": u.mean([c.f.words for c in rows]),
            "avg_tone": u.mean([c.f.score for c in rows if (c.f.pos + c.f.neg) > 0]),
            "question_share": u.share(sum(1 for c in rows if c.f.question), len(rows)),
        }
    by_id = {c.id: c for c in comments}
    to_new = to_old = old_to_new = 0
    tone_to_new: list[float] = []
    tone_to_old: list[float] = []
    for c in comments:
        parent = by_id.get(c.parent_id) if c.parent_id else None
        if not parent or parent.from_id is None or parent.from_id <= 0:
            continue
        pkey, ckey = (parent.platform, parent.from_id), (c.platform, c.from_id)
        if pkey in new:
            to_new += 1
            if ckey in old:
                old_to_new += 1
            if c.f.pos + c.f.neg:
                tone_to_new.append(c.f.score)
        elif pkey in old:
            to_old += 1
            if c.f.pos + c.f.neg:
                tone_to_old.append(c.f.score)
    return {
        "boundary_first_seen": boundary.isoformat(),
        **stats,
        "interactions": {
            "replies_to_newcomers": to_new,
            "replies_to_oldtimers": to_old,
            "oldtimers_replying_to_newcomers": old_to_new,
            "avg_tone_of_replies_to_newcomers": u.mean(tone_to_new),
            "avg_tone_of_replies_to_oldtimers": u.mean(tone_to_old),
        },
        "note": "стаж считается по первому появлению в наших данных (дата вступления в группу недоступна без админ-токена)",
    }
