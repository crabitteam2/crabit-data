"""Generate causal intentions through the real persistent backend, never final-row inserts."""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path
import json
import platform
import resource
import subprocess
import time

from .policy import (END, START, POLICY_VERSION, canonical, digest, grants, instant,
                     local_day, monthly_budget, population, periods, rng_for,
                     target_amount, traits, visits)
from .runtime import Session, services

ACTIVE = {'IN_PROGRESS', 'AMOUNT_REACHED'}
PASSIVE = {'GRANT', 'PURCHASE', 'CLOSE_WEEK', 'CLOSE_MONTH', 'INFLUENCED_DECISION'}


class Policy:
    def __init__(self, session, people, seed):
        self.session, self.people, self.seed = session, people, seed
        self.seq = 0
        self.day = None
        self.day_tick = 0
        self.wishes, self.wish_owner, self.wish_created = {}, {}, {}
        self.cards, self.card_wishes = {}, {}
        self.preferred, self.goal_number, self.last_goal_end = {}, Counter(), {}
        self.deleted, self.influenced = set(), set()
        self.last_activity, self.cash, self.following, self.blocked = {}, {}, set(), {}
        self.joined = set()
        self.counts, self.outcomes = Counter(), Counter()

    def emit(self, person, day, kind, command, causes=(), boundary=False):
        if day != self.day:
            self.day, self.day_tick = day, 0
        self.seq += 1
        self.day_tick += 1
        event_id, result_ref = f'e{self.seq}', f'raw/results/{self.seq}.json'
        when = instant(day) if boundary else instant(day, 12, self.day_tick * 1000)
        event = dict(eventId=event_id, sequence=self.seq, occurredAt=when,
                     actorStudentId=person['logicalStudentId'], kind=kind, causes=list(causes),
                     command=command, outcome=dict(status='APPLIED', resultRef=result_ref),
                     artifactRefs=[result_ref] + [value for key, value in command.items() if key.endswith('Ref')])
        observed = self.session.step(event)
        event, result = observed['event'], observed['result']
        status = event['outcome']['status']
        self.counts[kind] += 1
        self.outcomes[status] += 1
        sid = person['logicalStudentId']
        if kind not in PASSIVE:
            self.last_activity[sid] = event
        if status == 'APPLIED':
            if kind == 'JOIN':
                self.joined.add(sid)
                self.cash[sid] = 0
            if kind in ('GRANT', 'PURCHASE'):
                self.cash[sid] = result['cardFunds']
            if kind == 'BALANCE_LOOKUP':
                self.cash[sid] = result['balance']
            if kind == 'CREATE':
                self.wish_owner[command['wishId']] = sid
                self.wish_created[command['wishId']] = day
            if 'wish' in result and 'wishId' in command:
                self.wishes[command['wishId']] = result['wish']
            if kind == 'TRANSFER':
                self.wishes[command['sourceWishId']] = result['sourceWish']
                self.wishes[command['destinationWishId']] = result['destinationWish']
            if kind in ('COMPLETE', 'ABANDON'):
                self.last_goal_end[sid] = day
            if kind == 'DELETE':
                self.deleted.add(command['wishId'])
            if kind == 'FOLLOW':
                self.following.add((sid, command['ownerStudentId']))
            if kind == 'UNFOLLOW':
                self.following.discard((sid, command['ownerStudentId']))
            if kind == 'BLOCK':
                self.blocked[(sid, command['ownerStudentId'])] = day
                self.following.discard((sid, command['ownerStudentId']))
            if kind == 'UNBLOCK':
                self.blocked.pop((sid, command['ownerStudentId']), None)
            for identity in observed['newIdentities']:
                if identity.startswith('SHARED_CARD:'):
                    card = identity.split(':', 1)[1]
                    self.cards[card] = person
                    self.card_wishes[card] = command['wishId']
        if kind.startswith('CLOSE_') and (status != 'APPLIED' or result.get('state') not in ('SUCCEEDED', 'NOT_ELIGIBLE')):
            raise RuntimeError(f'mandatory closure failed: {event_id}: {result}')
        return event, result

    def active(self, person):
        sid = person['logicalStudentId']
        return [wid for wid, owner in self.wish_owner.items()
                if owner == sid and wid not in self.deleted and self.wishes[wid]['state'] in ACTIVE]

    def allocation(self, person):
        return sum(self.wishes[wid]['amount'] for wid in self.active(person))

    def mutate(self, person, day, kind, wish_id, causes=(), **extra):
        return self.emit(person, day, kind, dict(accountId=person['logicalAccountId'], wishId=wish_id,
                         expectedVersion=self.wishes[wish_id]['version'], idempotencyKey=f'policy-{self.seq+1}', **extra), causes)

    def create(self, person, day, source=None, causes=()):
        sid, tr = person['logicalStudentId'], traits(person)
        self.goal_number[sid] += 1
        number = self.goal_number[sid]
        wish_id = f'wish-{sid}-{number}'
        interest = tr['interest'] if number % 2 else tr['secondaryInterest']
        amount = target_amount(self.seed, sid, number)
        if source is not None:
            interest = source['purpose'][:100] + ' 도전'
            amount = max(5000, min(200000, source['targetAmount'] // 2000 * 1000))
        target_date = str(day + timedelta(days=30 if amount <= 20000 else 90 if amount <= 70000 else 180)) if tr['hasTargetDate'] else None
        event, result = self.emit(person, day, 'CREATE', dict(
            accountId=person['logicalAccountId'], wishId=wish_id, idempotencyKey=wish_id,
            purpose=interest, targetAmount=amount, startDate=str(day), targetDate=target_date, photoId=None), causes)
        if event['outcome']['status'] == 'APPLIED':
            self.preferred[sid] = wish_id
            if not person['isOwner']:
                self.share(person, day, wish_id, tr['privacy'])
        return event, result

    def share(self, person, day, wish_id, visibility, changed=False):
        return self.emit(person, day, 'VISIBILITY_CHANGE' if changed else 'SHARE', dict(
            accountId=person['logicalAccountId'], wishId=wish_id,
            expectedVersion=self.wishes[wish_id]['version'], visibility=visibility))

    def social(self, person, day, operation, other, causes=()):
        assert not person['isOwner'] and not other['isOwner']
        assert other['logicalStudentId'] in self.joined
        return self.emit(person, day, operation, dict(academyId='academy-1',
                         viewerStudentId=person['logicalStudentId'], ownerStudentId=other['logicalStudentId']), causes)

    def classmates(self, person):
        tr = traits(person)
        peers = [p for p in self.people if not p['isOwner'] and p != person and p['logicalStudentId'] in self.joined]
        return sorted(peers, key=lambda p: (traits(p)['friendGroup'] != tr['friendGroup'], p['grade'] != person['grade'], p['logicalStudentId']))

    def observe(self, person, day):
        return self.emit(person, day, 'BALANCE_LOOKUP', dict(accountId=person['logicalAccountId'],
                         observationRef=f'raw/balance/b{self.seq+1}.json'))

    def adjust_after_observation(self, person, day, observed_event):
        """One explicit student withdrawal; no automatic mutation of desired final balances."""
        sid = person['logicalStudentId']
        deficit = self.allocation(person) - self.cash[sid]
        if deficit <= 0:
            return
        available = sorted(self.active(person), key=lambda wid: -self.wishes[wid]['amount'])
        if available and self.wishes[available[0]]['amount']:
            self.mutate(person, day, 'WITHDRAW', available[0], [observed_event['eventId']],
                        amount=min(deficit, self.wishes[available[0]]['amount']))

    def goal_actions(self, person, day, rng):
        sid, tr = person['logicalStudentId'], traits(person)
        active = self.active(person)
        for wid in list(active):
            wish = self.wishes[wid]
            if wish['state'] == 'AMOUNT_REACHED' and rng.randrange(100) < tr['completionConfirmationPercent']:
                self.mutate(person, day, 'COMPLETE', wid, confirmed=True)
            elif ((day - self.wish_created[wid]).days >= 21 and wish['state'] == 'IN_PROGRESS'
                  and rng.random() < 0.035):
                self.mutate(person, day, 'ABANDON', wid)
        active = self.active(person)
        last_end = self.last_goal_end.get(sid, local_day(person['joinedAt']))
        if not active and (day - last_end).days >= tr['goalCooldownDays']:
            self.create(person, day)
        elif len(active) < tr['goalCapacity'] and active and rng.random() < 0.08:
            self.create(person, day)
        active = self.active(person)
        if not active:
            return
        chosen = self.preferred.get(sid)
        if chosen not in active:
            chosen = active[0]
        wish = self.wishes[chosen]
        free = max(0, self.cash[sid] - self.allocation(person))
        # A visit is a decision occasion, not a prescribed classification or completion count.
        if free and wish['state'] == 'IN_PROGRESS' and rng.random() < 0.70:
            amount = min(free, wish['targetAmount'] - wish['amount'],
                         max(100, monthly_budget(self.seed, person, str(day)[:7]) * tr['allocationPercent'] // 800))
            if amount:
                self.mutate(person, day, 'DEPOSIT', chosen, amount=amount)
        current = self.wishes[chosen]
        if current['state'] == 'AMOUNT_REACHED' and rng.randrange(100) < tr['completionConfirmationPercent']:
            self.mutate(person, day, 'COMPLETE', chosen, confirmed=True)
        elif current['state'] in ACTIVE and current['amount'] >= 500 and rng.random() < 0.04:
            self.mutate(person, day, 'WITHDRAW', chosen, amount=500)
        active = self.active(person)
        if len(active) >= 2 and rng.random() < 0.12:
            source, destination = active[:2]
            amount = min(1000, self.wishes[source]['amount'],
                         self.wishes[destination]['targetAmount'] - self.wishes[destination]['amount'])
            if amount > 0:
                event_id = f'e{self.seq+1}'
                self.emit(person, day, 'TRANSFER', dict(accountId=person['logicalAccountId'],
                          sourceWishId=source, destinationWishId=destination, amount=amount,
                          sourceExpectedVersion=self.wishes[source]['version'], destinationExpectedVersion=self.wishes[destination]['version'],
                          idempotencyKey=f'transfer-{event_id}', rootEventId=f'root-{event_id}',
                          sourceEffectId=f'out-{event_id}', destinationEffectId=f'in-{event_id}'))
        for wid, owner in list(self.wish_owner.items()):
            if (owner == sid and wid not in self.deleted and self.wishes[wid]['state'] not in ACTIVE
                    and (day - self.wish_created[wid]).days >= 28 and rng.random() < 0.035):
                self.mutate(person, day, 'DELETE', wid)
                break
        active = self.active(person)
        if active and rng.random() < 0.035:
            visibility = rng.choices(['ACADEMY', 'FOLLOWERS', 'PRIVATE'], [50, 30, 20])[0]
            self.share(person, day, active[0], visibility, changed=True)

    def influence(self, person, day, signal, card, rng):
        sid, tr = person['logicalStudentId'], traits(person)
        key = (sid, day.year, day.month)
        if (not tr['influenceSusceptible'] or key in self.influenced or rng.random() >= 0.30
                or signal['outcome']['status'] != 'APPLIED'):
            return
        source = self.wishes.get(self.card_wishes.get(card))
        if source is None:
            return
        active = self.active(person)
        decision = None
        if len(active) < tr['goalCapacity']:
            decision, _ = self.create(person, day, source, [signal['eventId']])
        elif active and self.cash[sid] > self.allocation(person):
            # The actually observed goal chooses the nearest personal goal and saving magnitude.
            selected = max(active, key=lambda wid: (self.wishes[wid]['purpose'].split()[0] in source['purpose'], -abs(self.wishes[wid]['targetAmount'] - source['targetAmount'])))
            wish = self.wishes[selected]
            amount = min(self.cash[sid] - self.allocation(person), wish['targetAmount'] - wish['amount'], max(100, source['targetAmount'] // 20))
            if amount > 0:
                decision, _ = self.mutate(person, day, 'DEPOSIT', selected, [signal['eventId']], amount=amount)
                if decision['outcome']['status'] == 'APPLIED':
                    self.preferred[sid] = selected
        if decision is not None:
            self.influenced.add(key)
            self.emit(person, day, 'INFLUENCED_DECISION', dict(signalType=signal['kind'],
                      signalEventId=signal['eventId'], decisionEventId=decision['eventId']),
                      [signal['eventId'], decision['eventId']])

    def feed(self, person, day, rng, previous=None):
        context, prefix = f'ctx-{self.seq+1}', f'raw/feed/f{self.seq+1}'
        feed, result = self.emit(person, day, 'FEED_QUERY', dict(academyId='academy-1', limit=5,
                                 cursor=None if previous is None else f"event:{previous['eventId']}:nextCursor",
                                 resultContextId=context, orderedCardIds=[], requestRef=prefix+'-request.json',
                                 responseRef=prefix+'-response.json'), [] if previous is None else [previous['eventId']])
        if feed['outcome']['status'] != 'APPLIED':
            return feed, result
        cards = feed['command']['orderedCardIds']
        # Record actual visible slots; a returned-but-unseen slot is not an exposure.
        visible = min(len(cards), rng.choice([1, 1, 2]))
        for position, card in enumerate(cards[:visible]):
            impression_id = f'imp-{self.seq+1}'
            impression, _ = self.emit(person, day, 'IMPRESSION', dict(academyId='academy-1', resultContextId=context,
                                      cardId=card, position=position, impressionId=impression_id), [feed['eventId']])
            if impression['outcome']['status'] != 'APPLIED':
                continue
            signal = impression
            if rng.randrange(100) < traits(person)['socialCuriosity']:
                click, _ = self.emit(person, day, 'CLICK', dict(academyId='academy-1', resultContextId=context,
                                    cardId=card, position=position, impressionId=impression_id, clickKind='AUTHOR_PROFILE'), [impression['eventId']])
                target = self.cards.get(card)
                if target and target != person and not target['isOwner'] and click['outcome']['status'] == 'APPLIED':
                    if rng.random() < 0.75:
                        signal, _ = self.emit(person, day, 'PROFILE_VISIT', dict(academyId='academy-1', targetStudentId=target['logicalStudentId'],
                                              source='FEED', sourceEventId=click['eventId']), [click['eventId']])
                    else:
                        signal = click
                    if rng.random() < 0.15 and (person['logicalStudentId'], target['logicalStudentId']) not in self.following:
                        self.social(person, day, 'FOLLOW', target, [signal['eventId']])
            self.influence(person, day, signal, card, rng)
        if len(cards) > visible and rng.random() < 0.04:
            # Contract permits unmatched clicks; never label these as exposure-based influence.
            self.emit(person, day, 'CLICK', dict(academyId='academy-1', resultContextId=context,
                      cardId=cards[visible], position=visible, impressionId=f'unmatched-{self.seq+1}', clickKind='AUTHOR_PROFILE'), [feed['eventId']])
        return feed, result

    def visit(self, person, day):
        sid = person['logicalStudentId']
        rng = rng_for(self.seed, 'visit-actions', sid, str(day))
        observed, _ = self.observe(person, day)
        self.adjust_after_observation(person, day, observed)
        self.goal_actions(person, day, rng)
        peers = self.classmates(person)
        if peers and rng.random() < 0.18:
            target = rng.choice(peers[:min(5, len(peers))]) if rng.random() < 0.80 else rng.choice(peers)
            if (sid, target['logicalStudentId']) not in self.following:
                self.social(person, day, 'FOLLOW', target)
        for (viewer, target_sid), blocked_at in list(self.blocked.items()):
            if viewer == sid and (day - blocked_at).days >= 14:
                target = next(p for p in peers if p['logicalStudentId'] == target_sid)
                self.social(person, day, 'UNBLOCK', target)
        followed = [p for p in peers if (sid, p['logicalStudentId']) in self.following]
        if followed and rng.random() < 0.06:
            self.social(person, day, 'BLOCK' if rng.random() < 0.30 else 'UNFOLLOW', rng.choice(followed))
        feed, result = self.feed(person, day, rng)
        if result.get('nextCursor') and rng.random() < 0.06:
            self.feed(person, day, rng, feed)
        if peers and rng.random() < 0.12:
            # Independent profile visits are retained with DIRECT provenance and no invented click.
            target = rng.choice(peers[:min(5, len(peers))])
            self.emit(person, day, 'PROFILE_VISIT', dict(academyId='academy-1', targetStudentId=target['logicalStudentId'], source='DIRECT', sourceEventId=None))

    def run(self):
        closures = {}
        for day, _, person, start, kind in periods(self.people):
            closures.setdefault(day, []).append((person, start, kind))
        schedules = {(p['logicalStudentId'], month): grants(self.seed, p, 2026, month)
                     for p in self.people for month in range(6, 10)}
        day = START
        while day < END:
            for person, start, kind in closures.get(day, []):
                prefix = f'raw/close/c{self.seq+1}'
                self.emit(person, day, kind, dict(accountId=person['logicalAccountId'], startInclusive=str(start),
                          endExclusive=str(day), generationId=f'g{self.seq+1}', snapshotRef=prefix+'-snapshot.json',
                          requestRef=prefix+'-request.json', responseRef=prefix+'-response.json', storedStateRef=prefix+'-stored.json'), boundary=True)
            for person in self.people:
                if local_day(person['joinedAt']) == day:
                    self.emit(person, day, 'JOIN', dict(studentId=person['logicalStudentId'], accountId=person['logicalAccountId'], academyId='academy-1', grade=person['grade']), boundary=True)
            for person in self.people:
                sid, tr = person['logicalStudentId'], traits(person)
                if sid not in self.joined:
                    continue
                amount = schedules[(sid, day.month)].get(day)
                if amount is not None:
                    self.emit(person, day, 'GRANT', dict(accountId=person['logicalAccountId'], amountKrw=amount,
                              cashEntryId=f'cash-{self.seq+1}', budgetMonth=str(day)[:7], scheduledAt=instant(day, 12)))
                # Independent real card purchases are passive, including during app dormancy.
                if day.day in (6, 13, 20, 27) and not person['isOwner']:
                    amount = min(self.cash[sid], monthly_budget(self.seed, person, str(day)[:7]) * tr['spendingPercent'] // 400)
                    if amount > 0:
                        self.emit(person, day, 'PURCHASE', dict(accountId=person['logicalAccountId'], amountKrw=amount, cashEntryId=f'cash-{self.seq+1}'))
                joined_today = local_day(person['joinedAt']) == day
                if joined_today:
                    self.create(person, day)
                if person['isOwner']:
                    continue
                dormancy_start = date(2026, 7, 8)
                dormancy_end = dormancy_start + timedelta(days=tr['dormancyDays'])
                if tr['dormantJuly']:
                    if day == dormancy_start - timedelta(days=1):
                        self.observe(person, day)
                    if dormancy_start <= day < dormancy_end:
                        continue
                    if day == dormancy_end:
                        anchor = self.last_activity[sid]
                        # The last app event is on July7; the maximum gap is under21days.
                        self.emit(person, day, 'RETURN_FROM_DORMANCY', dict(priorDormancyEventId=anchor['eventId']), [anchor['eventId']])
                week = day - timedelta(days=day.weekday())
                scheduled = day in visits(self.seed, person, week)
                if joined_today or scheduled or (tr['dormantJuly'] and day == dormancy_end):
                    self.visit(person, day)
            print(json.dumps({'day': str(day), 'completedEvents': self.seq, 'counts': dict(self.counts), 'outcomes': dict(self.outcomes)}, ensure_ascii=False), flush=True)
            day += timedelta(days=1)
        return self.session.finish()


def source_inventory(root):
    paths = sorted([p for folder in ('synthetic_data','scripts/demo','feed','feed_service','recap_service','recap')
                    for p in (root/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.java','.sh','.kts','.gradle')])
    return {str(path.relative_to(root)): digest(path.read_bytes()) for path in paths if path.is_file()}


def generate(output, backend, seed=20260910):
    root, backend, output = Path(__file__).resolve().parents[1], Path(backend).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    people = population(seed)
    shas = {repo: subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root if repo == 'crabit-data' else root.parent/repo, text=True).strip()
            for repo in ['crabit-backend', 'crabit-data', 'crabit-frontend']}
    inventory = source_inventory(root)
    config = dict(schemaVersion=1, seed=seed, timezone='Asia/Seoul', startInclusive=instant(START), endExclusive=instant(END),
                  academyCount=1, population=100, grades=[3, 4, 5, 6], studentsPerGrade=25, initialStudentsPerGrade=20, laterStudentsPerGrade=5,
                  assumptions=['All students and traits are synthetic assumptions, not measured child behavior.',
                               'Owner private/passive/isolated; local100 differs from applied originalOwner+99.',
                               'Weekly/monthly/irregular grants use the full calendar schedule; partial periods retain scheduled grants only.',
                               'Allocation reserves existing money; PURCHASE alone spends cash. App dormancy preserves passive grants and purchases.',
                               'Code SHAs identify Git HEAD; the uncommitted local source overlay is separately hashed.',
                               'sourceOverlayDigest='+digest(inventory)],
                  policyVersion=POLICY_VERSION, namespace='demo-student-behavior-simulation',
                  monthlyBudgetRules=dict(minimumKrw=10000, maximumKrw=30000, partialMonthPolicy='ACTUAL_SCHEDULED_GRANTS_ONLY'),
                  runtimeVersions=dict(java='21', postgresql='16', python=platform.python_version(), node=subprocess.check_output(['node', '--version'], text=True).strip(),
                                       feedModel='feed-rules-v1', recapModel='recap-1'))
    binding = dict(schemaVersion=1, configDigest=digest(config), codeShas=shas, normalizationVersion=1)
    dataset = digest(binding)
    personas = [dict(persona=f'grade-{grade}', grade=grade, displayName=f'{grade}학년 대표',
                    logicalStudentId=f'student-{grade}-01', logicalAccountId=f'account-{grade}-01') for grade in range(3, 7)]
    for name, value in [('config', config), ('students', people), ('binding', binding), ('personas', personas), ('source-inventory', inventory),
                        ('policy-session', dict(schemaVersion=1, datasetId=dataset, inputDigest=digest(config), students=people))]:
        (output/f'{name}.json').write_bytes(canonical(value))
    session, start = None, time.monotonic()
    try:
        with services(root, output) as environment:
            try:
                session = Session(backend, output/'policy-session.json', output/'discovery', environment, output)
                observation = Policy(session, people, seed).run()
                (output/'generation-result.json').write_bytes(canonical(observation))
            finally:
                if session:
                    session.close()
    finally:
        files = [path for path in output.rglob('*') if path.is_file()]
        (output/'measurement.json').write_bytes(canonical(dict(
            elapsedSeconds=round(time.monotonic()-start, 3), pythonPeakRssBytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            directChildPeakRssBytes=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
            jvmResourceUsageRef='jvm-resource-usage.txt', fileCount=len(files), artifactBytes=sum(path.stat().st_size for path in files),
            readyForApplication=False)))
