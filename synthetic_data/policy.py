"""Versioned, assumption-based inputs. No final savings classes or balances are assigned."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import random

KST = timezone(timedelta(hours=9), 'Asia/Seoul')
START = date(2026, 6, 1)
END = date(2026, 9, 11)
POLICY_VERSION = 'outcome-policy-v2'
INTERESTS = ('축구공', '색연필', '과학 실험 키트', '보드게임', '책 세트', '배드민턴 라켓', '블록 세트', '헤드폰')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return 'sha256:' + hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def rng_for(seed, *parts):
    return random.Random(int.from_bytes(hashlib.sha256(canonical([seed, *parts])).digest(), 'big'))


def instant(day, hour=0, microseconds=0):
    dt = datetime.combine(day, datetime.min.time(), KST).replace(hour=hour) + timedelta(microseconds=microseconds)
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def local_day(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(KST).date()


def traits(person):
    return {entry['name']: entry['value'] for entry in person['archetypeInputs']}


def population(seed=20260910):
    people = []
    later = [date(2026, 7, 1), date(2026, 7, 15), date(2026, 8, 1), date(2026, 8, 17), date(2026, 9, 3)]
    for grade in range(3, 7):
        for index in range(25):
            sid = f'student-{grade}-{index:02}'
            rng = rng_for(seed, 'person', sid)
            owner = grade == 3 and index == 0
            join = START if index < 20 else later[index - 20]
            inputs = {
                'monthlyEarnedKrw': rng.randrange(10, 31) * 1000,
                'grantCadence': rng.choice(['WEEKLY', 'MONTHLY', 'IRREGULAR']),
                'interest': rng.choice(INTERESTS),
                'secondaryInterest': rng.choice(INTERESTS),
                'allocationPercent': rng.randrange(30, 76),
                'spendingPercent': rng.randrange(25, 71),
                'visitFrequency': 'PASSIVE' if owner else rng.choices(['FREQUENT', 'INFREQUENT'], [25, 75])[0],
                'privacy': 'PRIVATE' if owner else rng.choices(['ACADEMY', 'FOLLOWERS', 'PRIVATE'], [50, 30, 20])[0],
                'ownerPolicy': 'PRIVATE_PASSIVE_ISOLATED' if owner else 'SYNTHETIC',
                'dormantJuly': not owner and join < date(2026, 7, 1) and rng.random() < 0.20,
                'dormancyDays': rng.choice([7, 14, 19]),
                'socialCuriosity': rng.randrange(25, 91),
                'influenceSusceptible': not owner and rng.random() < 0.30,
                'completionConfirmationPercent': rng.randrange(60, 96),
                'goalCapacity': 1 if owner else rng.choices([1, 2, 3], [60, 32, 8])[0],
                'goalCooldownDays': rng.choice([3, 7, 14]),
                'friendGroup': f'{grade}-{index // 5}',
                'hasTargetDate': rng.random() < 0.75,
            }
            people.append(dict(
                logicalStudentId=sid, logicalAccountId=f'account-{grade}-{index:02}',
                logicalAcademyId='academy-1', grade=grade, syntheticDisplayName=f'가상{grade}학년{index+1:02}',
                joinedAt=instant(join), archetypeInputs=[{'name': name, 'value': value} for name, value in inputs.items()],
                isOwner=owner,
            ))
    return people


def target_amount(seed, student_id, goal_number):
    rng = rng_for(seed, 'goal', student_id, goal_number)
    band = rng.choices(['SMALL', 'MEDIUM', 'LARGE'], [76, 18, 6])[0]
    low, high = {'SMALL': (5, 20), 'MEDIUM': (21, 70), 'LARGE': (71, 200)}[band]
    return rng.randrange(low, high + 1) * 1000


def monthly_budget(seed, person, month):
    base = traits(person)['monthlyEarnedKrw']
    adjustment = rng_for(seed, 'monthly-budget', person['logicalStudentId'], month).choice([-2000, -1000, 0, 1000, 2000])
    return min(30000, max(10000, base + adjustment))


def grants(seed, person, year, month):
    """Full calendar schedule first; enrollment/cutoff filtering happens at execution."""
    tr = traits(person)
    rng = rng_for(seed, 'grant-schedule', person['logicalStudentId'], year, month)
    budget = monthly_budget(seed, person, f'{year:04}-{month:02}')
    if tr['grantCadence'] == 'MONTHLY':
        days, weights = [1], [1]
    elif tr['grantCadence'] == 'WEEKLY':
        days, weights = [1, 8, 15, 22], [1, 1, 1, 1]
    else:
        days = sorted(rng.sample(range(1, calendar.monthrange(year, month)[1] + 1), 3))
        weights = [rng.randrange(1, 5) for _ in days]
    amounts = [budget * weight // sum(weights) for weight in weights]
    amounts[-1] += budget - sum(amounts)
    return dict(zip((date(year, month, day) for day in days), amounts))


def visits(seed, person, week_start):
    tr = traits(person)
    rng = rng_for(seed, 'visits', person['logicalStudentId'], str(week_start))
    frequency = tr['visitFrequency']
    count = 0 if frequency == 'PASSIVE' else rng.randrange(3, 6) if frequency == 'FREQUENT' else rng.randrange(0, 3)
    return {week_start + timedelta(days=n) for n in rng.sample(range(7), count)}


def periods(people):
    result = []
    for person in people:
        joined = local_day(person['joinedAt'])
        boundary = START + timedelta(days=7)
        while boundary < END:
            beginning = boundary - timedelta(days=7)
            if beginning >= joined:
                result.append((boundary, 0, person, beginning, 'CLOSE_WEEK'))
            boundary += timedelta(days=7)
        for month in (7, 8, 9):
            boundary, beginning = date(2026, month, 1), date(2026, month - 1, 1)
            if beginning >= joined:
                result.append((boundary, 1, person, beginning, 'CLOSE_MONTH'))
    return sorted(result, key=lambda x: (x[0], x[1], x[2]['logicalStudentId']))
