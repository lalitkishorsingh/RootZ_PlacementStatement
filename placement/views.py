import csv
import io
import json
from datetime import timedelta
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction, IntegrityError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from . import access, audit, services
from .auth_views import recent
from .forms import (StudentForm, CompanyForm, DriveForm, OfferForm, ReasonForm, ReviewForm,
                    AttendanceForm, OfferUpdateForm, StrictFormMixin)
from .models import (Student, Company, Drive, Offer, Application, SignupRequest, User, Review,
                     Attendance, ExceptionGrant, Policy, AuditEvent, ImportBatch, Sanction, COURSES)
from .policy import evaluate, category, DEFAULT
from .imports import parse_upload, safe_cell, COLUMNS

def failure(request, exc):
    messages.error(request,' '.join(exc.messages) if isinstance(exc,ValidationError) else 'A duplicate record or concurrent change was rejected.')

def staff_form(request, form, title, on_save, back='dashboard'):
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic(): on_save(form)
            messages.success(request,'Changes saved securely.')
            return redirect(back)
        except (ValidationError,IntegrityError) as exc: form.add_error(None, ' '.join(exc.messages) if isinstance(exc,ValidationError) else 'Duplicate or conflicting record.')
    return render(request,'form.html',{'form':form,'title':title,'submit':'Save changes'})

@login_required
def dashboard(request):
    if request.user.role=='recruiter':
        audit.record(request.user,'report.recruiter_dashboard',details={'company_id':request.user.company_id})
        return render(request,'dashboard.html',{'recruiter':True,'company':request.user.company,'applications':access.applications(request.user)[:8],
                     'offers':access.offers(request.user).filter(verified=False)[:8]})
    stats = services.report(request.user,request.GET.get('course',''),request.GET.get('batch',''))
    audit.record(request.user,'report.dashboard',details={'course':request.GET.get('course',''),'batch':request.GET.get('batch','')})
    breakdown = []
    if request.user.role in access.STAFF:
        for code,label in COURSES:
            if request.user.role=='coordinator' and code not in request.user.courses: continue
            item = services.report(request.user,code,request.GET.get('batch',''))
            breakdown.append({'name':label,'total':item['total'],'placed':item['placed'],'unplaced':item['unplaced']})
    return render(request,'dashboard.html',{'stats':stats,'breakdown':breakdown,'courses':COURSES,
                                         'offers':access.offers(request.user).order_by('-issued_at')[:6]})

@login_required
def students(request):
    qs = access.students(request.user).filter(archived=False)
    query,course,batch = request.GET.get('q','')[:100],request.GET.get('course',''),request.GET.get('batch','')[:20]
    if query:
        from django.db.models import Q
        qs = qs.filter(Q(name__icontains=query)|Q(placement_id__icontains=query))
    if course: qs = qs.filter(course=course)
    if batch: qs = qs.filter(batch=batch)
    rows = list(qs.order_by('placement_id')[:200])
    for item in rows: item.placement_status = services.placement_status(item)
    audit.record(request.user,'student.list',details={'count':len(rows),'course':course,'batch':batch})
    return render(request,'students.html',{'students':rows,'courses':COURSES})

@login_required
def student_detail(request, pk):
    student = get_object_or_404(access.students(request.user),pk=pk)
    audit.record(request.user,'student.read',pk,{'fields':['name','course','contact','placement']})
    # Recruiters never receive other organizations' offers, compensation or review cases.
    own_offers = access.offers(request.user).filter(student=student)
    reviews = Review.objects.filter(student=student) if request.user.role!='recruiter' else Review.objects.none()
    available = []
    if request.user.role!='recruiter':
        for drive in access.drives(request.user).filter(open=True,closes_at__gt=timezone.now()).order_by('scheduled_at'):
            if student.course in drive.courses: available.append({'drive':drive,'decision':evaluate(student,drive)})
    return render(request,'student.html',{'student':student,'offers':own_offers,'reviews':reviews,
                                        'placement_status':services.placement_status(student),'available':available})

@login_required
def student_edit(request, pk=None):
    access.require_staff(request.user)
    instance = get_object_or_404(access.students(request.user),pk=pk) if pk else None
    form = StudentForm(request.POST or None,instance=instance)
    if request.user.role=='coordinator': form.fields['course'].choices = [(c,n) for c,n in COURSES if c in request.user.courses]
    def save(form):
        original = Student.objects.select_for_update().get(pk=instance.pk) if instance else None
        if original and not access.students(request.user).filter(pk=original.pk).exists(): raise PermissionDenied
        before = {'course':original.course,'registration':original.registration,'eligibility':original.eligibility} if original else {}
        student = form.save()
        audit.record(request.user,'student.update' if instance else 'student.create',student.pk,
                     {'before':before,'after':{'course':student.course,'registration':student.registration,'eligibility':student.eligibility},'changed_fields':form.changed_data})
    return staff_form(request,form,'Update student record' if instance else 'Create student record',save,'students')

@login_required
def archive(request, pk):
    access.require_staff(request.user)
    student = get_object_or_404(access.students(request.user),pk=pk)
    form = ReasonForm(request.POST or None)
    def save(form):
        item = Student.objects.select_for_update().get(pk=student.pk)
        if not access.students(request.user).filter(pk=item.pk).exists(): raise PermissionDenied
        item.archived,item.archived_at = True,timezone.now()
        item.save(update_fields=['archived','archived_at'])
        if item.user_id:
            user = User.objects.select_for_update().get(pk=item.user_id)
            user.is_active = False
            user.credential_version += 1
            user.save()
        audit.record(request.user,'student.archive',pk,{'reason':form.cleaned_data['reason']})
    return staff_form(request,form,'Archive student record',save,'students')

@login_required
def companies(request):
    access.require_staff(request.user)
    return render(request,'companies.html',{'companies':Company.objects.order_by('name')})

@login_required
def company_create(request):
    if request.user.role not in {'admin','officer'}: raise PermissionDenied
    form = CompanyForm(request.POST or None)
    def save(form):
        company = form.save()
        audit.record(request.user,'company.create',company.pk)
    return staff_form(request,form,'Add recruiting organization',save,'companies')

@login_required
def drives(request):
    rows = []
    for drive in access.drives(request.user).order_by('scheduled_at'):
        if request.user.role=='student' and request.user.student.course not in drive.courses: continue
        drive.category = category(drive.ctc)
        rows.append({'drive':drive,'decision':evaluate(request.user.student,drive) if request.user.role=='student' else None})
    audit.record(request.user,'drive.list',details={'count':len(rows)})
    return render(request,'drives.html',{'rows':rows})

@login_required
def drive_edit(request, pk=None):
    if request.user.role not in {'admin','officer'}: raise PermissionDenied
    instance = get_object_or_404(Drive,pk=pk) if pk else None
    form = DriveForm(request.POST or None,instance=instance)
    def save(form):
        drive = form.save()
        audit.record(request.user,'drive.update' if instance else 'drive.create',drive.pk,{'changed_fields':form.changed_data})
    return staff_form(request,form,'Configure recruitment drive',save,'drives')

@login_required
@require_POST
def apply(request, pk):
    drive = get_object_or_404(access.drives(request.user),pk=pk)
    try: services.apply(request.user,drive); messages.success(request,'Application submitted for staff approval.')
    except (ValidationError,IntegrityError) as exc: failure(request,exc)
    return redirect('applications')

@login_required
def applications(request):
    audit.record(request.user,'application.list')
    return render(request,'applications.html',{'applications':access.applications(request.user).order_by('-created_at')[:200]})

@login_required
@require_POST
def application_review(request, pk):
    access.require_staff(request.user)
    item = get_object_or_404(access.applications(request.user),pk=pk)
    action = request.POST.get('action')
    if action not in {'approve','reject'}: raise PermissionDenied
    try: services.approve_application(request.user,item,action=='approve'); messages.success(request,'Application reviewed.')
    except ValidationError as exc: failure(request,exc)
    return redirect('applications')

@login_required
def offer_create(request, pk):
    student = get_object_or_404(access.students(request.user),pk=pk)
    form = OfferForm(request.POST or None,initial={'issued_at':timezone.localtime().strftime('%Y-%m-%dT%H:%M'),'off_campus':request.user.role=='student'})
    if request.user.role=='recruiter':
        form.fields['company'].queryset = Company.objects.filter(pk=request.user.company_id)
        form.fields['drive'].queryset = access.drives(request.user).filter(application__student=student,application__status='approved')
    elif request.user.role=='student': form.fields['drive'].queryset = Drive.objects.none()
    def save(form): services.submit_offer(request.user,student,form.cleaned_data)
    return staff_form(request,form,'Submit offer for verification',save,'offers')

@login_required
def offers(request):
    qs = access.offers(request.user).order_by('-issued_at')[:200]
    audit.record(request.user,'offer.list',details={'count':len(qs),'fields':['compensation','acceptance','joining']})
    return render(request,'offers.html',{'offers':qs})

@login_required
@require_POST
def offer_action(request, pk):
    offer = get_object_or_404(access.offers(request.user),pk=pk)
    action = request.POST.get('action')
    try:
        if action=='verify': services.verify_offer(request.user,offer)
        elif action in {'accepted','declined'}:
            if not services.respond_offer(request.user,offer,action):
                messages.error(request,'The acceptance deadline has passed.')
                return redirect('offers')
        else: raise PermissionDenied
        messages.success(request,'Offer updated.')
    except (ValidationError,IntegrityError) as exc: failure(request,exc)
    return redirect('offers')

@login_required
def offer_update(request, pk):
    access.require_staff(request.user)
    instance = get_object_or_404(access.offers(request.user),pk=pk)
    form = OfferUpdateForm(request.POST or None,instance=instance)
    def save(form):
        student = Student.objects.select_for_update().get(pk=instance.student_id)
        if not access.students(request.user).filter(pk=student.pk).exists(): raise PermissionDenied
        item = Offer.objects.select_for_update().get(pk=instance.pk)
        if not item.verified: raise ValidationError('Verify this offer first.')
        if item.withdrawn and not form.cleaned_data['withdrawn']: raise ValidationError('Withdrawals cannot be reversed; submit a new reviewed offer.')
        if form.cleaned_data['joining']=='joined' and item.acceptance!='accepted': raise ValidationError('Joining requires an accepted offer.')
        if form.cleaned_data['ppo']!='na' and item.offer_type=='F': raise ValidationError('FTE-only offers do not have PPO status.')
        before = {f:getattr(item,f) for f in ('ppo','joining','noc','withdrawn')}
        for field in before: setattr(item,field,form.cleaned_data[field])
        item.save()
        audit.record(request.user,'offer.administrative_update',pk,{'before':before,'after':{f:getattr(item,f) for f in before},'reason':form.cleaned_data['reason']})
    return staff_form(request,form,'Update PPO, joining and NOC',save,'offers')

@login_required
def review_create(request, pk):
    if request.user.role=='recruiter': raise PermissionDenied
    student = get_object_or_404(access.students(request.user),pk=pk)
    form = ReviewForm(request.POST or None)
    def save(form):
        item = Review.objects.create(student=student,**form.cleaned_data)
        audit.record(request.user,'review.create',item.pk,{'kind':item.kind})
    return staff_form(request,form,'Request a Placement Cell review',save,'reviews')

@login_required
def reviews(request):
    if request.user.role=='recruiter': raise PermissionDenied
    return render(request,'reviews.html',{'reviews':Review.objects.filter(student__in=access.students(request.user)).select_related('student').order_by('-created_at')[:200]})

@login_required
def review_resolve(request, pk):
    access.require_staff(request.user)
    item = get_object_or_404(Review,pk=pk,student__in=access.students(request.user))
    class Form(ReasonForm):
        action = forms.ChoiceField(choices=[('approve','Approve / emergency exception'),('reject','Reject')]+([('sanction','Exclude next three eligible drives')] if request.user.role=='admin' and item.kind=='absence' else []))
    form = Form(request.POST or None)
    def save(form): services.resolve_review(request.user,item,form.cleaned_data['action'],form.cleaned_data['reason'])
    return staff_form(request,form,'Resolve review case',save,'reviews')

@login_required
def attendance(request, pk):
    access.require_staff(request.user)
    student = get_object_or_404(access.students(request.user),pk=pk)
    form = AttendanceForm(request.POST or None)
    form.fields['drive'].queryset = Drive.objects.filter(application__student=student,application__status='approved')
    def save(form):
        Student.objects.select_for_update().get(pk=pk)
        item = Attendance.objects.create(student=student,**form.cleaned_data)
        if not item.present:
            Review.objects.create(student=student,kind='absence',details=f'Absent from {item.activity} at drive {item.drive_id}.')
        audit.record(request.user,'attendance.record',item.pk,{'present':item.present,'activity':item.activity})
    return staff_form(request,form,'Record recruitment attendance',save,'students')

@login_required
def exception(request, pk, drive_pk):
    access.require_admin(request.user)
    if not recent(request): return redirect('reauth')
    student,drive = get_object_or_404(Student,pk=pk),get_object_or_404(Drive,pk=drive_pk)
    form = ReasonForm(request.POST or None)
    def save(form):
        Student.objects.select_for_update().get(pk=pk)
        item = ExceptionGrant.objects.create(student=student,drive=drive,reason=form.cleaned_data['reason'],expires=drive.scheduled_at+timedelta(days=1),approved_by=request.user)
        audit.record(request.user,'policy.exception',item.pk,{'student':str(pk),'drive':drive.pk,'reason':item.reason,'expires':item.expires.isoformat()})
    return staff_form(request,form,'Approve a drive-specific policy exception',save,'students')

@login_required
def accounts(request):
    access.require_admin(request.user)
    audit.record(request.user,'account.directory_read')
    pending = SignupRequest.objects.filter(user__approved=False,user__email_verified=True).select_related('user')
    return render(request,'accounts.html',{'pending':pending,'accounts':User.objects.order_by('role','username')})

@login_required
def approve_signup(request, pk):
    access.require_admin(request.user)
    if not recent(request): return redirect('reauth')
    signup = get_object_or_404(SignupRequest,user_id=pk,user__approved=False,user__email_verified=True)
    class Form(ReasonForm):
        student = forms.ModelChoiceField(queryset=Student.objects.filter(user__isnull=True,archived=False))
    form = Form(request.POST or None)
    def save(form):
        user = User.objects.select_for_update().get(pk=pk)
        student = Student.objects.select_for_update().get(pk=form.cleaned_data['student'].pk)
        if student.user_id or user.approved: raise ValidationError('Account or record was already linked.')
        if student.email.lower()!=user.email.lower() or student.placement_id!=signup.placement_id or student.course!=signup.course:
            raise ValidationError('Registered email, Placement ID and course must match the verified institutional record. Correct the record after independent verification if necessary.')
        student.user = user
        student.save(update_fields=['user'])
        user.approved = True
        user.save(update_fields=['approved'])
        audit.record(request.user,'account.approve',pk,{'student':str(student.pk),'reason':form.cleaned_data['reason']})
    return staff_form(request,form,'Approve verified student account',save,'accounts')

@login_required
def account_edit(request, pk):
    access.require_admin(request.user)
    if not recent(request): return redirect('reauth')
    user = get_object_or_404(User,pk=pk)
    from .forms import InviteForm
    class Form(InviteForm):
        is_active = forms.BooleanField(required=False)
        reason = forms.CharField(min_length=10,max_length=2000)
        reset_mfa = forms.BooleanField(required=False,label='Reset authenticator after independent identity verification')
    initial = {'email':user.email,'role':user.role,'courses':user.courses,'company':user.company_id,'is_active':user.is_active}
    form = Form(request.POST or None,initial=initial)
    # Accounts cannot switch between student and staff; provisioning uses distinct reviewed workflows.
    if user.role=='student': form.fields['role'].choices = [('student','Student')]
    form.fields['email'].disabled = True
    def save(form):
        if user.pk==request.user.pk: raise ValidationError('Administrators cannot change their own authorization.')
        item = User.objects.select_for_update().get(pk=pk)
        before = {'role':item.role,'courses':item.courses,'company_id':item.company_id,'is_active':item.is_active}
        for field in ('role','courses','company','is_active'): setattr(item,field,form.cleaned_data[field])
        if form.cleaned_data['reset_mfa']:
            item.mfa_secret = ''
            item.mfa_enabled = False
            item.mfa_last_step = -1
            audit.record(request.user,'account.mfa_recovery',pk,{'reason':form.cleaned_data['reason']})
        item.credential_version += 1
        item.save()
        audit.record(request.user,'account.authorization_update',pk,{'before':before,'after':{'role':item.role,'courses':item.courses,'company_id':item.company_id,'is_active':item.is_active},'reason':form.cleaned_data['reason']})
    return staff_form(request,form,'Manage account permissions',save,'accounts')

@login_required
def policy_settings(request):
    access.require_admin(request.user)
    if not recent(request): return redirect('reauth')
    class Form(ReasonForm):
        version = forms.CharField(max_length=40)
        b_min = forms.DecimalField(min_value=1,decimal_places=2,max_digits=8,initial=6)
        a_min = forms.DecimalField(min_value=1,decimal_places=2,max_digits=8,initial=10)
        aplus_min = forms.DecimalField(min_value=1,decimal_places=2,max_digits=8,initial=16)
        b_multiplier = forms.DecimalField(min_value=1,decimal_places=2,max_digits=4,initial=Decimal('1.5'))
        def clean(self):
            data = super().clean()
            if all(data.get(k) is not None for k in ('b_min','a_min','aplus_min')) and not data['b_min']<data['a_min']<data['aplus_min']:
                raise ValidationError('Category thresholds must be strictly increasing.')
            return data
    form = Form(request.POST or None)
    def save(form):
        # AuditHead is the common serialization lock for policy changes and audit events.
        from .models import AuditHead
        AuditHead.objects.select_for_update().get(pk=1)
        Policy.objects.filter(active=True).update(active=False)
        item = Policy.objects.create(version=form.cleaned_data['version'],active=True,config={k:str(form.cleaned_data[k]) for k in DEFAULT})
        audit.record(request.user,'policy.activate',item.version,{'config':item.config,'reason':form.cleaned_data['reason']})
    return staff_form(request,form,'Publish a new policy version',save)

@login_required
def audit_log(request):
    access.require_admin(request.user)
    audit.record(request.user,'audit.read')
    return render(request,'audit.html',{'events':AuditEvent.objects.order_by('-id')[:200]})

@login_required
def export(request):
    access.require_staff(request.user)
    if not recent(request): return redirect('reauth')
    class Form(StrictFormMixin,forms.Form):
        course = forms.ChoiceField(choices=[('','All authorized courses')]+COURSES,required=False)
        batch = forms.CharField(max_length=20,required=False)
        sensitive = forms.BooleanField(required=False,label='Include contact and compensation details')
        format = forms.ChoiceField(choices=[('csv','CSV'),('xlsx','Excel workbook')])
    form = Form(request.POST or None)
    if request.method=='POST' and form.is_valid():
        data = form.cleaned_data
        qs = access.students(request.user).filter(archived=False).order_by('placement_id')
        if data['course']: qs = qs.filter(course=data['course'])
        if data['batch']: qs = qs.filter(batch=data['batch'])
        fields = ['Placement ID','Name','Course','Batch','Registration','Eligibility','Placement status']
        if data['sensitive']: fields += ['Email','Mobile','Accepted annual CTC (LPA)']
        rows = [fields]
        for student in qs:
            row = [student.placement_id,student.name,student.get_course_display(),student.batch,student.registration,student.eligibility,services.placement_status(student)]
            if data['sensitive']:
                row += [student.email,student.mobile,'; '.join(o.ctc for o in student.offers.filter(verified=True,withdrawn=False,acceptance='accepted').exclude(offer_type='I') if o.ctc)]
            rows.append([safe_cell(value) for value in row])
        audit.record(request.user,'export.students',details={'fields':fields,'filters':{'course':data['course'],'batch':data['batch']},'count':len(rows)-1})
        if data['format']=='csv':
            stream = io.StringIO(); csv.writer(stream).writerows(rows)
            response = HttpResponse('\ufeff'+stream.getvalue(),content_type='text/csv; charset=utf-8')
        else:
            from openpyxl import Workbook
            workbook = Workbook(write_only=True); sheet = workbook.create_sheet('NFSU Placement')
            for row in rows: sheet.append(row)
            stream = io.BytesIO(); workbook.save(stream)
            response = HttpResponse(stream.getvalue(),content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="nfsu-placement.{data["format"]}"'
        response['Cache-Control'] = 'no-store'
        return response
    return render(request,'form.html',{'form':form,'title':'Export authorized placement records','subtitle':'Downloads contain institutional data. Every export is audited.','submit':'Download report'})

@login_required
def reports(request):
    access.require_staff(request.user)
    from .reporting import institutional_report
    course,batch=request.GET.get('course',''),request.GET.get('batch','')[:20]
    data=institutional_report(request.user,course,batch)
    audit.record(request.user,'report.institutional',details={'course':course,'batch':batch})
    data['courses']=COURSES
    return render(request,'reports.html',data)

@login_required
def import_records(request):
    access.require_staff(request.user)
    class Form(StrictFormMixin,forms.Form):
        file = forms.FileField()
    form = Form(request.POST or None,request.FILES or None)
    if request.method=='POST' and form.is_valid():
        try:
            rows, errors = parse_upload(form.cleaned_data['file'],request.user)
            if errors: return render(request,'import.html',{'form':form,'errors':errors})
            batch = ImportBatch.objects.create(owner=request.user,payload=json.dumps(rows))
            audit.record(request.user,'import.preview',batch.pk,{'count':len(rows)})
            return redirect('import_preview',pk=batch.pk)
        except ValidationError as exc: form.add_error(None,exc)
    return render(request,'import.html',{'form':form,'columns':','.join(COLUMNS)})

@login_required
def import_preview(request, pk):
    access.require_staff(request.user)
    item = get_object_or_404(ImportBatch,pk=pk,owner=request.user,committed=False,created_at__gt=timezone.now()-timedelta(hours=1))
    if request.method=='POST':
        try:
            with transaction.atomic():
                item = ImportBatch.objects.select_for_update().get(pk=pk)
                if item.committed or item.created_at<=timezone.now()-timedelta(hours=1): raise ValidationError('Preview expired or was already committed.')
                for row in json.loads(item.payload):
                    form = StudentForm(row)
                    if not form.is_valid(): raise ValidationError('Import is no longer valid. Preview again.')
                    if request.user.role=='coordinator' and row['course'] not in request.user.courses: raise PermissionDenied
                    form.save()
                item.committed = True; item.payload = ''; item.save()
                audit.record(request.user,'import.commit',pk)
            messages.success(request,'Import committed atomically.')
            return redirect('students')
        except (ValidationError,IntegrityError) as exc: failure(request,exc)
    return render(request,'import_preview.html',{'rows':json.loads(item.payload),'batch':item})

def health(request):
    try:
        from django.db import connection
        with connection.cursor() as cursor: cursor.execute('SELECT 1')
        return JsonResponse({'status':'ok'})
    except Exception: return JsonResponse({'status':'unavailable'},status=503)
