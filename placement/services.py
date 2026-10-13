from datetime import timedelta
from statistics import mean, median
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from . import access, audit
from .models import Student, Application, Offer, Drive, Review, Sanction
from .policy import evaluate, amount

@transaction.atomic
def apply(user, drive):
    if user.role != 'student': raise PermissionDenied
    student = Student.objects.select_for_update().get(user=user)
    decision = evaluate(student, drive)
    if decision.outcome != 'allowed': raise ValidationError(decision.explanations)
    application = Application.objects.create(student=student, drive=drive, decision=decision.data())
    audit.record(user, 'application.create', application.pk, decision.data())
    return application

@transaction.atomic
def approve_application(user, application, approve):
    access.require_staff(user)
    if not access.students(user).filter(pk=application.student_id).exists(): raise PermissionDenied
    student = Student.objects.select_for_update().get(pk=application.student_id)
    if not access.students(user).filter(pk=student.pk).exists(): raise PermissionDenied
    application = Application.objects.select_for_update().select_related('drive').get(pk=application.pk)
    if application.status != 'submitted': raise ValidationError('Application was already reviewed.')
    decision = evaluate(student, application.drive)
    if approve and decision.outcome != 'allowed': raise ValidationError(decision.explanations)
    application.status = 'approved' if approve else 'rejected'
    application.decision = decision.data()
    application.save()
    audit.record(user, 'application.review', application.pk, {'status':application.status, 'policy':decision.data()})

@transaction.atomic
def submit_offer(user, student, cleaned):
    if not access.students(user).filter(pk=student.pk).exists(): raise PermissionDenied
    if user.role == 'student' and not cleaned.get('off_campus'): raise PermissionDenied
    if user.role == 'recruiter':
        drive = cleaned.get('drive')
        if not drive or drive.company_id != user.company_id or not Application.objects.filter(student=student, drive=drive, status='approved').exists():
            raise PermissionDenied
        if cleaned['company'].pk != user.company_id: raise PermissionDenied
    locked = Student.objects.select_for_update().get(pk=student.pk)
    if not access.students(user).filter(pk=locked.pk).exists() or locked.archived: raise PermissionDenied
    issued = cleaned['issued_at']
    if issued > timezone.now() + timedelta(minutes=5): raise ValidationError('Offer issuance cannot be in the future.')
    deadline = min(issued + timedelta(hours=24), cleaned.get('company_deadline') or issued + timedelta(hours=24))
    offer = Offer.objects.create(student=student, submitted_by=user, deadline=deadline, **cleaned)
    audit.record(user, 'offer.submit', offer.pk, {'student':str(student.pk), 'off_campus':offer.off_campus})
    return offer

@transaction.atomic
def verify_offer(user, offer):
    access.require_staff(user)
    if not access.students(user).filter(pk=offer.student_id).exists(): raise PermissionDenied
    student = Student.objects.select_for_update().get(pk=offer.student_id)
    if not access.students(user).filter(pk=student.pk).exists(): raise PermissionDenied
    offer = Offer.objects.select_for_update().select_related('drive').get(pk=offer.pk)
    if offer.verified or offer.withdrawn: raise ValidationError('Offer is already verified or withdrawn.')
    if offer.drive:
        if offer.company_id != offer.drive.company_id or offer.offer_type != offer.drive.offer_type:
            raise ValidationError('Company and offer type must match the drive.')
        if not Application.objects.filter(student=student, drive=offer.drive, status='approved').exists():
            raise ValidationError('An approved application is required.')
        # Evaluate actual compensation, not an earlier advertised figure.
        opportunity = Drive.objects.get(pk=offer.drive_id)
        opportunity.ctc = offer.ctc
        decision = evaluate(student, opportunity, exclude_offer=offer.pk, check_open=False)
    else:
        opportunity = Drive(company=offer.company, offer_type=offer.offer_type, ctc=offer.ctc,
                            courses=[student.course], open=True, closes_at=timezone.now()+timedelta(days=1))
        decision = evaluate(student, opportunity, exclude_offer=offer.pk, check_open=False)
    if decision.outcome != 'allowed':
        raise ValidationError(decision.explanations)
    offer.verified = True
    offer.decision = decision.data()
    if offer.deadline <= timezone.now(): offer.acceptance = 'expired'
    offer.save()
    audit.record(user, 'offer.verify', offer.pk, decision.data())

@transaction.atomic
def respond_offer(user, offer, response):
    if user.role != 'student' or offer.student.user_id != user.pk: raise PermissionDenied
    Student.objects.select_for_update().get(pk=offer.student_id)
    offer = Offer.objects.select_for_update().get(pk=offer.pk)
    if response not in {'accepted','declined'}: raise ValidationError('Invalid response.')
    if not offer.verified or offer.withdrawn or offer.acceptance != 'pending': raise ValidationError('This offer cannot receive a response.')
    if timezone.now() >= offer.deadline:
        offer.acceptance = 'expired'
        offer.save(update_fields=['acceptance'])
        audit.record(user, 'offer.expire', offer.pk)
        return False
    offer.acceptance = response
    offer.save(update_fields=['acceptance'])
    audit.record(user, 'offer.respond', offer.pk, {'response':response})
    return True

def placement_status(student):
    types = set(student.offers.filter(verified=True, withdrawn=False, acceptance='accepted').values_list('offer_type', flat=True))
    if 'IF' in types or {'I','F'} <= types: return 'Internship + PPO/FTE'
    if 'F' in types: return 'FTE only'
    if 'I' in types: return 'Internship only'
    return 'Unplaced'

def report(user, course='', batch=''):
    qs = access.students(user).filter(archived=False)
    if course: qs = qs.filter(course=course)
    if batch: qs = qs.filter(batch=batch)
    students = list(qs.prefetch_related('offers'))
    verified = Offer.objects.filter(student__in=qs, verified=True, withdrawn=False)
    accepted = list(verified.filter(acceptance='accepted').select_related('company'))
    placed = {o.student_id for o in accepted}
    packages = [amount(o.ctc) for o in accepted if o.offer_type != 'I' and amount(o.ctc) is not None]
    return {'total':len(students), 'registered':sum(s.registration=='registered' for s in students),
            'eligible':sum(s.eligibility=='eligible' for s in students), 'ineligible':sum(s.eligibility=='ineligible' for s in students),
            'placed':len(placed), 'unplaced':len(students)-len(placed), 'offers':verified.count(),
            'internship':sum(placement_status(s)=='Internship only' for s in students),
            'fte':sum(placement_status(s)=='FTE only' for s in students),
            'combined':sum(placement_status(s)=='Internship + PPO/FTE' for s in students),
            'highest':max(packages, default=0), 'average':round(mean(packages),2) if packages else 0,
            'median':median(packages) if packages else 0,
            'pending_acceptance':verified.filter(acceptance='pending',deadline__gt=timezone.now()).count(),
            'pending_joining':verified.filter(acceptance='accepted', joining='pending').count(),
            'pending_reviews':Review.objects.filter(student__in=qs,status='pending').count(), 'students':students}

@transaction.atomic
def resolve_review(user, review, action, reason):
    access.require_staff(user)
    if not access.students(user).filter(pk=review.student_id).exists(): raise PermissionDenied
    Student.objects.select_for_update().get(pk=review.student_id)
    review = Review.objects.select_for_update().get(pk=review.pk)
    if review.status != 'pending' or not reason.strip(): raise ValidationError('Pending review and a reason are required.')
    if action == 'sanction':
        access.require_admin(user)
        if review.kind != 'absence': raise ValidationError('Only absenteeism cases support attendance sanctions.')
        candidates = Drive.objects.filter(open=True,scheduled_at__gt=timezone.now()).order_by('scheduled_at','pk')
        chosen = [d for d in candidates if evaluate(review.student,d).outcome=='allowed'][:3]
        if len(chosen) != 3: raise ValidationError('Three scheduled eligible drives are required before issuing the sanction.')
        sanction = Sanction.objects.create(student=review.student, review=review, reason=reason)
        sanction.drives.set(chosen)
        review.status = 'approved'
    elif action in {'approve','reject'}:
        review.status = 'approved' if action == 'approve' else 'rejected'
    else: raise ValidationError('Invalid review action.')
    review.resolution = reason
    review.save()
    audit.record(user, 'review.resolve', review.pk, {'action':action,'reason':reason})
