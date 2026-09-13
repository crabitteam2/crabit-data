import unittest
from collections import Counter
from datetime import date,timedelta
from synthetic_data.policy import (population, periods, traits, instant, grants, visits,
                                   target_amount, monthly_budget, local_day)

class PolicyTest(unittest.TestCase):
    def test_population_owner_and_representatives(self):
        people=population(); self.assertEqual(people,population())
        self.assertNotEqual(people,population(7))
        self.assertEqual(Counter(p['grade'] for p in people),{3:25,4:25,5:25,6:25})
        self.assertEqual(sum(p['joinedAt']==instant(date(2026,6,1)) for p in people),80)
        self.assertEqual(sum(p['isOwner'] for p in people),1)
        for grade in range(3,7):
            rep=next(p for p in people if p['logicalStudentId']==f'student-{grade}-01')
            self.assertFalse(rep['isOwner'])
        owner=next(p for p in people if p['isOwner'])
        self.assertEqual(traits(owner)['privacy'],'PRIVATE')
        self.assertFalse(visits(20260910,owner,date(2026,6,1)))
    def test_full_month_budget_and_partial_calendar_schedule(self):
        people=population()
        self.assertEqual({traits(p)['grantCadence'] for p in people},{'WEEKLY','MONTHLY','IRREGULAR'})
        for p in people:
            for month in range(6,10):
                schedule=grants(20260910,p,2026,month)
                self.assertEqual(sum(schedule.values()),monthly_budget(20260910,p,f'2026-{month:02}'))
                self.assertTrue(10000<=sum(schedule.values())<=30000)
                self.assertTrue(all(amount>0 for amount in schedule.values()))
                eligible={d:a for d,a in schedule.items() if local_day(p['joinedAt'])<=d<date(2026,9,11)}
                self.assertLessEqual(sum(eligible.values()),sum(schedule.values()))
    def test_mandatory_complete_periods_no_future(self):
        people=population(); closure=periods(people)
        for p in people:
            if p['joinedAt']==instant(date(2026,6,1)):
                self.assertEqual(sum(x[2]==p and x[4]=='CLOSE_WEEK' for x in closure),14)
                self.assertEqual(sum(x[2]==p and x[4]=='CLOSE_MONTH' for x in closure),3)
        self.assertEqual(max(x[0] for x in closure),date(2026,9,7))
        self.assertTrue(all(instant(x[3])>=x[2]['joinedAt'] for x in closure))
    def test_assumptions_cover_plan_without_final_class_assignment(self):
        people=population(); amounts=[target_amount(20260910,p['logicalStudentId'],n) for p in people for n in range(1,5)]
        self.assertGreater(sum(5000<=x<=20000 for x in amounts),len(amounts)//2)
        self.assertTrue(any(20000<x<=70000 for x in amounts))
        self.assertTrue(any(70000<x<=200000 for x in amounts))
        for p in people:
            tr=traits(p)
            self.assertNotIn('savingsType',tr)
            for week in [date(2026,6,1)+timedelta(days=7*n) for n in range(14)]:
                count=len(visits(20260910,p,week))
                self.assertTrue(count==0 if tr['visitFrequency']=='PASSIVE' else 3<=count<=5 if tr['visitFrequency']=='FREQUENT' else 0<=count<=2)
        self.assertEqual({traits(p)['privacy'] for p in people},{'PRIVATE','FOLLOWERS','ACADEMY'})
if __name__=='__main__':unittest.main()
