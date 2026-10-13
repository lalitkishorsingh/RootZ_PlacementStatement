from django.core.exceptions import PermissionDenied
from .models import Student, Drive, Offer, Application, Review, User

STAFF = {User.Role.ADMIN, User.Role.OFFICER, User.Role.COORDINATOR}
PRIVILEGED = STAFF

def students(user):
    qs = Student.objects.all()
    if user.role in {User.Role.ADMIN, User.Role.OFFICER}: return qs
    if user.role == User.Role.COORDINATOR: return qs.filter(course__in=user.courses)
    if user.role == User.Role.STUDENT: return qs.filter(user=user)
    if user.role == User.Role.RECRUITER and user.company_id:
        return qs.filter(application__drive__company_id=user.company_id, application__status='approved').distinct()
    return qs.none()

def drives(user):
    qs = Drive.objects.select_related('company')
    if user.role == User.Role.RECRUITER: return qs.filter(company_id=user.company_id) if user.company_id else qs.none()
    if user.role == User.Role.STUDENT:
        try: course = user.student.course
        except Student.DoesNotExist: return qs.none()
        return qs.filter(open=True)  # JSON course filtering is done in views/policy, portable to local SQLite.
    return qs

def offers(user):
    qs = Offer.objects.select_related('student','company','drive')
    if user.role == User.Role.RECRUITER:
        return qs.filter(company_id=user.company_id) if user.company_id else qs.none()
    return qs.filter(student__in=students(user))

def applications(user):
    qs = Application.objects.select_related('student','drive','drive__company')
    if user.role == User.Role.RECRUITER:
        return qs.filter(drive__company_id=user.company_id, status='approved') if user.company_id else qs.none()
    return qs.filter(student__in=students(user))

def require_staff(user):
    if user.role not in STAFF: raise PermissionDenied

def require_admin(user):
    if user.role != User.Role.ADMIN: raise PermissionDenied
