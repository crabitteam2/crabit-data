"""Independent event/cash/allocation/access oracle over actual replay artifacts."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
import json
import re

from .policy import canonical, digest

SEOUL = timezone(timedelta(hours=9))
FROM = datetime(2026, 5, 31, 15, tzinfo=timezone.utc)
UNTIL = datetime(2026, 9, 10, 15, tzinfo=timezone.utc)


class InvalidDataset(ValueError):
    def __init__(self, rule, event_id, detail):
        self.rule, self.event_id, self.detail = rule, event_id, detail
        super().__init__(f'{rule}:{event_id}:{detail}')


def require(ok, rule, event='', detail=''):
    if not ok:
        raise InvalidDataset(rule, event, detail)


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def read_json(path):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise InvalidDataset('duplicate-json-key', '', key)
            out[key] = value
        return out
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique)


def expected_periods(people):
    expected = set()
    for person in people:
        joined = timestamp(person['joinedAt']).astimezone(SEOUL).date()
        day = date(2026, 6, 1)
        while day < date(2026, 9, 11):
            if day.weekday() == 0:
                first = day - timedelta(days=7)
                if first >= joined:
                    expected.add((person['logicalAccountId'], 'CLOSE_WEEK', str(first), str(day)))
            if day.day == 1:
                first = (day - timedelta(days=1)).replace(day=1)
                if first >= joined:
                    expected.add((person['logicalAccountId'], 'CLOSE_MONTH', str(first), str(day)))
            day += timedelta(days=1)
    return expected


def validate_population(people, personas):
    require(len(people) == 100, 'population', detail='100 students required')
    require(Counter(p['grade'] for p in people) == {3:25, 4:25, 5:25, 6:25}, 'grades')
    require(Counter(p['grade'] for p in people if timestamp(p['joinedAt']) == FROM) == {3:20, 4:20, 5:20, 6:20}, 'initial-enrollment')
    for p in people:
        joined = timestamp(p['joinedAt'])
        require(FROM <= joined < UNTIL and (joined == FROM or joined >= datetime(2026, 6, 30, 15, tzinfo=timezone.utc)), 'later-enrollment', p['logicalStudentId'])
    require(len({p['logicalStudentId'] for p in people}) == len({p['logicalAccountId'] for p in people}) == 100, 'identity-bijection')
    require(len({p['logicalAcademyId'] for p in people}) == 1 and sum(p['isOwner'] for p in people) == 1, 'owner-academy')
    by_id = {p['logicalStudentId']: p for p in people}
    require({p['persona'] for p in personas} == {'grade-3','grade-4','grade-5','grade-6'}, 'personas')
    require(len(personas) == 4, 'personas')
    for p in personas:
        person = by_id[p['logicalStudentId']]
        require(not person['isOwner'] and person['grade'] == p['grade'] and person['logicalAccountId'] == p['logicalAccountId'], 'persona-owner')


def verify_events(people, events, read_result, identities=None, *, require_complete=True):
    """Reconstruct balances/state from commands, then compare each observed mutation snapshot."""
    by_student = {p['logicalStudentId']: p for p in people}
    account_owner = {p['logicalAccountId']: p['logicalStudentId'] for p in people}
    owner = next(p['logicalStudentId'] for p in people if p['isOwner'])
    cash, cash_sequence, earnings = defaultdict(int), Counter(), Counter()
    wishes, card_wishes, contexts, prior = {}, {}, {}, {}
    follows, blocks, joined, closed = set(), set(), set(), set()
    visible = {}
    counts, statuses = Counter(), Counter()
    cash_rows = []
    previous_time, previous_sequence, previous_phase = FROM, 0, -1
    influence_count, matched_clicks, unmatched_clicks, recommended, latest = 0, 0, 0, 0, 0
    last_activity = {}
    identity_reverse = {}
    if identities:
        identity_reverse = {(e['entityKind'], e['replayUuid']): e['logicalId'] for e in identities['entries']}
    actual_cards = {e['logicalId'] for e in identities['entries'] if e['entityKind'] == 'SHARED_CARD'} if identities else None
    for event in events:
        eid, kind, sid, c = event['eventId'], event['kind'], event['actorStudentId'], event['command']
        when, status = timestamp(event['occurredAt']), event['outcome']['status']
        require(eid not in prior and event['sequence'] > previous_sequence, 'event-identity-order', eid)
        phase = 0 if kind == 'CLOSE_WEEK' else 1 if kind == 'CLOSE_MONTH' else 2
        require(FROM <= when < UNTIL and when >= previous_time, 'event-time', eid)
        require(when != previous_time or phase >= previous_phase, 'boundary-phase', eid)
        require(sid in by_student and when >= timestamp(by_student[sid]['joinedAt']), 'actor-enrollment', eid)
        require(len(event['causes']) == len(set(event['causes'])) and all(cause in prior for cause in event['causes']), 'causal-reference', eid)
        if kind == 'JOIN':
            require(sid not in joined and when == timestamp(by_student[sid]['joinedAt']), 'join', eid)
        else:
            require(sid in joined, 'join-before-action', eid)
        if 'accountId' in c:
            require(account_owner.get(c['accountId']) == sid, 'account-ownership', eid)
        if kind in ('FOLLOW','UNFOLLOW','BLOCK','UNBLOCK'):
            require(c['viewerStudentId'] == sid and c['ownerStudentId'] in joined, 'social-direction', eid)
            require(owner not in (sid, c['ownerStudentId']), 'owner-isolation', eid)
        if kind == 'PROFILE_VISIT':
            require(c['targetStudentId'] in joined and owner not in (sid, c['targetStudentId']), 'visit-membership-owner', eid)
        result = read_result(event)
        counts[kind] += 1
        statuses[status] += 1
        if status == 'APPLIED':
            if kind == 'JOIN':
                joined.add(sid)
            elif kind in ('GRANT','PURCHASE'):
                account, amount = c['accountId'], c['amountKrw']
                require(type(amount) is int and amount > 0, 'positive-cash', eid)
                if kind == 'GRANT':
                    scheduled = timestamp(c['scheduledAt'])
                    require(timestamp(by_student[sid]['joinedAt']) <= scheduled <= when and scheduled.astimezone(SEOUL).strftime('%Y-%m') == c['budgetMonth'], 'grant-schedule', eid)
                    earnings[(account, when.astimezone(SEOUL).strftime('%Y-%m'))] += amount
                cash[account] += amount if kind == 'GRANT' else -amount
                cash_sequence[account] += 1
                require(cash[account] >= 0, 'negative-cash', eid)
                require(result['cardFunds'] == cash[account], 'cash-response', eid)
                cash_rows.append(dict(id=c['cashEntryId'], eventId=eid, accountId=account, sequence=cash_sequence[account],
                                      occurredAt=event['occurredAt'], kind=kind, amountKrw=amount, balanceAfter=cash[account]))
            elif kind == 'BALANCE_LOOKUP':
                require(result['balance'] == cash[c['accountId']] and result['sourceKind'] == 'SIMULATION', 'balance-observation', eid)
            elif kind == 'CREATE':
                wid = c['wishId']
                require(wid not in wishes, 'wish-identity', eid)
                wishes[wid] = dict(owner=sid, account=c['accountId'], amount=0, target=c['targetAmount'],
                                   state='IN_PROGRESS', visibility='PRIVATE', deleted=False, created=when)
            elif kind in ('DEPOSIT','WITHDRAW','COMPLETE','ABANDON','DELETE','SHARE','VISIBILITY_CHANGE'):
                wid = c['wishId']
                require(wid in wishes and wishes[wid]['owner'] == sid and not wishes[wid]['deleted'], 'wish-owner-lifecycle', eid)
                wish = wishes[wid]
                if kind == 'DEPOSIT':
                    require(wish['state'] == 'IN_PROGRESS', 'deposit-state', eid)
                    wish['amount'] += c['amount']
                    wish['state'] = 'AMOUNT_REACHED' if wish['amount'] == wish['target'] else 'IN_PROGRESS'
                elif kind == 'WITHDRAW':
                    require(wish['state'] in ('IN_PROGRESS','AMOUNT_REACHED'), 'withdraw-state', eid)
                    wish['amount'] -= c['amount']
                    wish['state'] = 'AMOUNT_REACHED' if wish['amount'] == wish['target'] else 'IN_PROGRESS'
                elif kind == 'COMPLETE':
                    require(wish['state'] == 'AMOUNT_REACHED' and c['confirmed'] is True, 'completion-confirmation', eid)
                    wish['amount'], wish['state'] = 0, 'COMPLETED'
                elif kind == 'ABANDON':
                    require(wish['state'] in ('IN_PROGRESS','AMOUNT_REACHED'), 'abandonment-state', eid)
                    wish['amount'], wish['state'] = 0, 'ABANDONED'
                elif kind == 'DELETE':
                    wish['amount'], wish['deleted'] = 0, True
                else:
                    wish['visibility'] = c['visibility']
                    # The first actually materialized shared card owns the logical event identity.
                    if c['visibility'] != 'PRIVATE' and ((actual_cards is not None and eid in actual_cards) or (actual_cards is None and wid not in card_wishes.values())):
                        card_wishes[eid] = wid
                require(0 <= wish['amount'] <= wish['target'], 'wish-amount-range', eid)
            elif kind == 'TRANSFER':
                source, destination = wishes[c['sourceWishId']], wishes[c['destinationWishId']]
                require(source['owner'] == destination['owner'] == sid and c['sourceWishId'] != c['destinationWishId'], 'transfer-ownership', eid)
                require(source['state'] in ('IN_PROGRESS','AMOUNT_REACHED') and destination['state'] in ('IN_PROGRESS','AMOUNT_REACHED'), 'transfer-state', eid)
                source['amount'] -= c['amount']; destination['amount'] += c['amount']
                for wish in (source, destination):
                    require(0 <= wish['amount'] <= wish['target'], 'transfer-conservation', eid)
                    wish['state'] = 'AMOUNT_REACHED' if wish['amount'] == wish['target'] else 'IN_PROGRESS'
            elif kind == 'FOLLOW':
                follows.add((sid,c['ownerStudentId']))
            elif kind == 'UNFOLLOW':
                follows.discard((sid,c['ownerStudentId']))
            elif kind == 'BLOCK':
                blocks.add((sid,c['ownerStudentId'])); follows.discard((sid,c['ownerStudentId'])); follows.discard((c['ownerStudentId'],sid))
            elif kind == 'UNBLOCK':
                blocks.discard((sid,c['ownerStudentId']))
            elif kind == 'FEED_QUERY':
                require(sid != owner, 'owner-passive', eid)
                cards = c['orderedCardIds']
                require(len(cards) == len(set(cards)), 'feed-duplicate', eid)
                if result['sortSource'] == 'RECOMMENDATION':
                    require(result['modelVersion'] == 'feed-rules-v1', 'real-recommendation', eid)
                    recommended += 1
                else:
                    require(result['sortSource'] == 'LATEST' and result.get('modelVersion') is None, 'actual-latest-fallback', eid)
                    latest += 1
                if identities:
                    actual = [identity_reverse[('SHARED_CARD', item['sharedCardId'])] for item in result['items']]
                    require(cards == actual, 'feed-actual-order', eid)
                for card in cards:
                    require(card in card_wishes, 'feed-card-origin', eid, card)
                    wish = wishes[card_wishes[card]]; author = wish['owner']
                    require(author != sid and author in joined and author != owner, 'feed-membership', eid)
                    require(not wish['deleted'] and (sid,author) not in blocks and (author,sid) not in blocks, 'feed-block-delete', eid)
                    require(wish['visibility'] == 'ACADEMY' or (wish['visibility'] == 'FOLLOWERS' and (sid,author) in follows), 'feed-access', eid)
                contexts[c['resultContextId']] = (sid, cards)
            elif kind in ('IMPRESSION','CLICK'):
                require(c['resultContextId'] in contexts, 'context-reference', eid)
                actor,cards = contexts[c['resultContextId']]
                require(actor == sid and c['position'] < len(cards) and cards[c['position']] == c['cardId'], 'exposure-slot', eid)
                key=(sid,c['resultContextId'],c['cardId'],c['position'],c['impressionId'])
                if kind=='IMPRESSION': visible[key]=eid
                elif key in visible: matched_clicks += 1
                else: unmatched_clicks += 1
            elif kind == 'INFLUENCED_DECISION':
                signal, decision = prior.get(c['signalEventId']), prior.get(c['decisionEventId'])
                require(signal is not None and decision is not None and signal['sequence'] < decision['sequence'], 'influence-order', eid)
                require(signal['actorStudentId'] == decision['actorStudentId'] == sid and signal['kind'] == c['signalType'], 'influence-actor', eid)
                require(signal['outcome']['status']=='APPLIED' and decision['kind'] in ('CREATE','DEPOSIT'), 'influence-decision', eid)
                require(c['signalEventId'] in event['causes'] and c['decisionEventId'] in event['causes'], 'influence-causes', eid)
                influence_count += 1
            elif kind == 'RETURN_FROM_DORMANCY':
                anchor = prior[c['priorDormancyEventId']]
                require(last_activity.get(sid) == anchor['eventId'], 'dormancy-last-activity', eid)
                gap = when - timestamp(anchor['occurredAt'])
                require(timedelta(days=7) <= gap <= timedelta(days=21), 'dormancy-gap', eid)
            elif kind in ('CLOSE_WEEK','CLOSE_MONTH'):
                require(when == datetime.combine(date.fromisoformat(c['endExclusive']),datetime.min.time(),SEOUL), 'close-boundary', eid)
                key=(c['accountId'],kind,c['startInclusive'],c['endExclusive'])
                require(key not in closed and result['state'] in ('SUCCEEDED','NOT_ELIGIBLE'), 'close-state', eid)
                closed.add(key)
            if actual_cards is not None and eid in actual_cards and 'wishId' in c:
                card_wishes[eid] = c['wishId']
            if 'wish' in result and 'wishId' in c:
                expected, observed = wishes[c['wishId']], result['wish']
                require(observed['amount']==expected['amount'] and observed['state']==expected['state'] and observed['targetAmount']==expected['target'], 'mutation-snapshot', eid)
            if kind == 'TRANSFER':
                for name,key in [('sourceWish','sourceWishId'),('destinationWish','destinationWishId')]:
                    expected=wishes[c[key]]; observed=result[name]
                    require(observed['amount']==expected['amount'] and observed['state']==expected['state'], 'transfer-snapshot', eid)
        if kind not in ('GRANT','PURCHASE','CLOSE_WEEK','CLOSE_MONTH','INFLUENCED_DECISION'):
            last_activity[sid] = eid
        prior[eid]=event
        previous_time,previous_sequence,previous_phase=when,event['sequence'],phase
    if not require_complete:
        return dict(status='PARTIAL_EVENTS_CHECKED',counts=dict(counts),outcomes=dict(statuses))
    require(joined == set(by_student), 'all-students-joined')
    require(closed == expected_periods(people), 'all-complete-periods', detail=f'missing={len(expected_periods(people)-closed)} extra={len(closed-expected_periods(people))}')
    for person in people:
        for month in ('2026-06','2026-07','2026-08'):
            first=datetime.fromisoformat(month+'-01T00:00:00+09:00')
            if timestamp(person['joinedAt']) <= first:
                require(10000 <= earnings[(person['logicalAccountId'],month)] <= 30000, 'monthly-earned-budget', person['logicalStudentId'], month)
    return dict(counts=dict(counts), outcomes=dict(statuses), wishes=wishes, cash=dict(cash), cashSequences=dict(cash_sequence),
                cashRows=cash_rows, earnings={f'{account}:{month}':amount for (account,month),amount in earnings.items()},
                periods=len(closed), influenceCount=influence_count, matchedClicks=matched_clicks,
                unmatchedClicks=unmatched_clicks, recommendationQueries=recommended, latestQueries=latest)


def validate_discovery(run):
    run=Path(run); replay=run/'discovery'
    observation=read_json(run/'generation-result.json')
    require(observation['status']=='DISCOVERY_COMPLETED', 'finish-required')
    people,personas=read_json(run/'students.json'),read_json(run/'personas.json')
    validate_population(people,personas)
    events=[json.loads(line) for line in (replay/'events.ndjson').read_text().splitlines()]
    identities=read_json(replay/'id-map.json')
    oracle=verify_events(people,events,lambda e:read_json(replay/e['outcome']['resultRef']),identities)
    state=read_json(replay/'state/export.json')
    actual_rows=state['ledger']
    require(len(actual_rows)==len(oracle['cashRows']), 'cash-ledger-count')
    for expected,actual in zip(oracle['cashRows'],actual_rows):
        expected=dict(expected);actual=dict(actual)
        expected['occurredAt']=timestamp(expected['occurredAt']);actual['occurredAt']=timestamp(actual['occurredAt'])
        require(expected==actual,'cash-ledger-row',expected['eventId'])
    for row in state['balances']:
        require(row['amountKrw']==oracle['cash'].get(row['accountId'],0) and row['sequence']==oracle['cashSequences'].get(row['accountId'],0),'cash-cache',row['accountId'])
    relational=read_json(replay/'state/relational.json');tables=relational['tables']
    mapping={(e['entityKind'],e['logicalId']):e['replayUuid'] for e in identities['entries']}
    rows={w['id']:w for w in tables['wish']}
    for logical,wish in oracle['wishes'].items():
        row=rows[mapping['WISH',logical]]
        require(row['wish_amount']==wish['amount'] and row['state']==wish['state'] and (row['deleted_at'] is not None)==wish['deleted'],'relational-wish',logical)
    require(len(rows)==len(oracle['wishes']),'relational-wish-count')
    for flag in ('cashReconciliationPerformed','allocationReconciliationPerformed','observationReconciliationPerformed',
                 'relationalReferencesVerified','behaviorReconciliationPerformed','behaviorAccessReconciliationPerformed',
                 'influenceAnnotationsVerified','dormancyAnnotationsVerified','validationDatabaseUnchanged',
                 'monthlyBudgetReconciliationPerformed','allStudentsJoined','relationalTemporalAndHistoryVerified',
                 'historicalCheckpointsVerified','adjustmentEpisodesVerified','typedIdentityMapExported',
                 'idempotencyReconciliationPerformed','feedExchangeNormalizationPerformed',
                 'relationalIdentityNormalizationPerformed','allRelationalRuntimeValuesNormalized',
                 'responseNormalizationPerformed','backendLogicalProjectionExported'):
        require(observation.get(flag) is True,'backend-independent-verification',detail=flag)
    raw=read_json(replay/'raw/index.json')
    total_bytes,max_bytes=0,0
    for entry in raw['records']:
        path=replay/entry['path']; size=path.stat().st_size
        require(size==entry['byteLength'] and digest(path.read_bytes())==entry['sha256'],'raw-integrity',entry['eventId'],entry['path'])
        total_bytes+=size;max_bytes=max(max_bytes,size)
    absent=set(observation.get('absentRecapResponses',[]))
    legitimately_absent=set()
    for event in events:
        if event['kind'] in ('CLOSE_WEEK','CLOSE_MONTH'):
            outcome=read_json(replay/event['outcome']['resultRef'])
            if outcome['state']=='NOT_ELIGIBLE':
                require(outcome['pythonInvoked'] is False,'ineligible-no-http',event['eventId'])
                legitimately_absent.add(event['command']['responseRef'])
    require(absent==legitimately_absent,'missing-recap-raw',detail='Only actual NOT_ELIGIBLE may have no HTTP response')
    result={k:v for k,v in oracle.items() if k not in ('wishes','cashRows','cashSequences')}
    result.update(status='PASS',actualStudents=len(people),rawRecords=len(raw['records']),rawBytes=total_bytes,maxRawBytes=max_bytes,
                  sourceManifestBinding='POLICY_DISCOVERY',notEligibleWithoutHttpResponses=len(legitimately_absent),fullFixedReplaysVerified=False,readyForApplication=False)
    return result
