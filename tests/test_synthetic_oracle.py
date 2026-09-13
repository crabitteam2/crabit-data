"""Mutation tests over command/receipt evidence, independent of generator branches."""
import copy
import unittest
from synthetic_data.validate import InvalidDataset, verify_events

class OracleTest(unittest.TestCase):
    def setUp(self):
        self.people=[dict(logicalStudentId=s,logicalAccountId='a-'+s,logicalAcademyId='academy',joinedAt='2026-05-31T15:00:00Z',grade=3,isOwner=s=='owner') for s in ('owner','alice','bob')]
        self.events=[];self.results={}
        for person in self.people:
            self.add('JOIN',person['logicalStudentId'],dict(studentId=person['logicalStudentId'],accountId=person['logicalAccountId']),{},time='2026-05-31T15:00:00Z')
        self.add('GRANT','alice',dict(accountId='a-alice',cashEntryId='grant',amountKrw=10000,scheduledAt='2026-06-01T00:00:00Z',budgetMonth='2026-06'),dict(cardFunds=10000))
        self.add('CREATE','alice',dict(accountId='a-alice',wishId='wish',targetAmount=5000),dict(wish=dict(amount=0,state='IN_PROGRESS',targetAmount=5000)))
        self.add('DEPOSIT','alice',dict(accountId='a-alice',wishId='wish',amount=2000),dict(wish=dict(amount=2000,state='IN_PROGRESS',targetAmount=5000)))

    def add(self,kind,actor,command,result,causes=None,time=None):
        n=len(self.events)+1;eid=f'e{n}'
        self.events.append(dict(eventId=eid,sequence=n,kind=kind,actorStudentId=actor,occurredAt=time or f'2026-06-01T03:00:00.{n:06d}Z',causes=causes or [],command=command,outcome=dict(status='APPLIED')))
        self.results[eid]=result;return eid

    def verify(self):
        return verify_events(self.people,self.events,lambda e:self.results[e['eventId']],require_complete=False)

    def test_valid_cash_and_allocation_are_separate(self):
        self.assertEqual('PARTIAL_EVENTS_CHECKED',self.verify()['status'])

    def test_fabricated_cash_balance_is_rejected(self):
        self.results['e4']['cardFunds']=12000
        with self.assertRaisesRegex(InvalidDataset,'cash-response'):self.verify()

    def test_fabricated_wish_balance_is_rejected(self):
        self.results['e6']['wish']['amount']=3000
        with self.assertRaisesRegex(InvalidDataset,'mutation-snapshot'):self.verify()

    def test_future_causal_reference_is_rejected(self):
        self.events[-1]['causes']=['e999']
        with self.assertRaisesRegex(InvalidDataset,'causal-reference'):self.verify()

    def test_followers_card_requires_viewer_to_author_follow(self):
        shared=self.add('SHARE','alice',dict(wishId='wish',visibility='FOLLOWERS'),{})
        self.add('FOLLOW','alice',dict(viewerStudentId='alice',ownerStudentId='bob'),{})
        self.add('FEED_QUERY','bob',dict(orderedCardIds=[shared],resultContextId='ctx'),dict(sortSource='RECOMMENDATION',modelVersion='feed-rules-v1'))
        with self.assertRaisesRegex(InvalidDataset,'feed-access'):self.verify()

    def test_click_does_not_fabricate_missing_impression(self):
        shared=self.add('SHARE','alice',dict(wishId='wish',visibility='ACADEMY'),{})
        self.add('FEED_QUERY','bob',dict(orderedCardIds=[shared],resultContextId='ctx'),dict(sortSource='RECOMMENDATION',modelVersion='feed-rules-v1'))
        self.add('CLICK','bob',dict(resultContextId='ctx',cardId=shared,position=0,impressionId='not-emitted'),{})
        self.assertEqual('PARTIAL_EVENTS_CHECKED',self.verify()['status'])
        self.events[-1]['command']['position']=1
        with self.assertRaisesRegex(InvalidDataset,'exposure-slot'):self.verify()

    def test_partial_run_cannot_pass_full_validation(self):
        with self.assertRaisesRegex(InvalidDataset,'all-complete-periods'):
            verify_events(self.people,self.events,lambda e:self.results[e['eventId']])
