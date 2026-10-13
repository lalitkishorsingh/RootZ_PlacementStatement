from collections import defaultdict
from statistics import mean, median
from django.utils import timezone
from . import access
from .models import Offer, Drive
from .policy import amount, category, evaluate

def institutional_report(user, course='', batch=''):
    student_qs=access.students(user).filter(archived=False)
    if course: student_qs=student_qs.filter(course=course)
    if batch: student_qs=student_qs.filter(batch=batch)
    cohorts=defaultdict(lambda:{'total':0,'placed':set()})
    students=list(student_qs.prefetch_related('offers'))
    for student in students:
        key=(student.get_course_display(),student.batch)
        cohorts[key]['total']+=1
        if any(o.verified and not o.withdrawn and o.acceptance=='accepted' for o in student.offers.all()):
            cohorts[key]['placed'].add(student.pk)
    companies={}
    for offer in Offer.objects.filter(student__in=student_qs,verified=True,withdrawn=False).select_related('company'):
        row=companies.setdefault(offer.company_id,{'name':offer.company.name,'offers':0,'placed':set(),'packages':[],'categories':set(),'stipends':[]})
        row['offers']+=1
        if offer.ctc: row['categories'].add(category(offer.ctc) or 'Unclassified')
        if offer.acceptance=='accepted':
            row['placed'].add(offer.student_id)
            if offer.offer_type!='I' and amount(offer.ctc) is not None: row['packages'].append(amount(offer.ctc))
            if offer.stipend: row['stipends'].append(f'₹{offer.stipend} / {offer.get_stipend_period_display()}')
    for row in companies.values():
        row['placed']=len(row['placed']); row['categories']=', '.join(sorted(row['categories'])) or 'Internship only'
        row['highest']=max(row['packages'],default=0)
        row['average']=round(mean(row['packages']),2) if row['packages'] else 0
        row['median']=median(row['packages']) if row['packages'] else 0
    eligibility=[]
    for drive in Drive.objects.filter(open=True,closes_at__gt=timezone.now()).select_related('company').order_by('scheduled_at'):
        relevant=[s for s in students if s.course in drive.courses]
        if not relevant: continue
        row={'drive':drive,'allowed':[],'blocked':0,'manual_review':0}
        for student in relevant:
            decision=evaluate(student,drive)
            if decision.outcome=='allowed': row['allowed'].append(student)
            else: row[decision.outcome]+=1
        eligibility.append(row)
    return {'cohorts':[{'course':c,'batch':b,'total':v['total'],'placed':len(v['placed']),'unplaced':v['total']-len(v['placed'])} for (c,b),v in sorted(cohorts.items())],
            'company_rows':list(companies.values()),'eligibility_rows':eligibility}
