from decimal import Decimal
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import Student, Drive, Offer, Company, COURSES, TYPES

class StrictFormMixin:
    """Reject extra business fields rather than silently dropping privilege injection."""
    def clean(self):
        cleaned = super().clean()
        extra = set(self.data) - set(self.fields) - {'csrfmiddlewaretoken'}
        if extra: raise ValidationError('Unexpected fields in request.')
        return cleaned

class LoginForm(StrictFormMixin, forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)

class SignupForm(StrictFormMixin, forms.Form):
    username = forms.RegexField(r'^[a-zA-Z0-9_.-]+$', max_length=150)
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput, min_length=12)
    name = forms.CharField(max_length=180)
    placement_id = forms.RegexField(r'^[A-Za-z0-9_-]+$', max_length=40)
    course = forms.ChoiceField(choices=COURSES)
    batch = forms.RegexField(r'^\d{4}[-–]\d{2,4}$', max_length=20, help_text='Example: 2026–28')
    mobile = forms.RegexField(r'^\+?[0-9]{10,15}$', required=False)
    def clean_password(self):
        from .models import User
        validate_password(self.cleaned_data['password'],user=User(username=self.cleaned_data.get('username',''),email=self.cleaned_data.get('email','')))
        return self.cleaned_data['password']
    def clean_email(self): return self.cleaned_data['email'].lower()

class StudentForm(StrictFormMixin, forms.ModelForm):
    email = forms.EmailField()
    mobile = forms.RegexField(r'^\+?[0-9]{10,15}$', required=False)
    placement_id = forms.RegexField(r'^[A-Za-z0-9_-]+$', max_length=40)
    batch = forms.RegexField(r'^\d{4}[-–]\d{2,4}$', max_length=20)
    academic_score = forms.DecimalField(min_value=0, max_value=10, max_digits=4, decimal_places=2, required=False)
    class Meta:
        model = Student
        fields = ['placement_id','name','email','mobile','course','batch','registration','eligibility','academic_score']

class CompanyForm(StrictFormMixin, forms.ModelForm):
    class Meta:
        model = Company
        fields = ['name','website']

class DriveForm(StrictFormMixin, forms.ModelForm):
    ctc = forms.DecimalField(label='Annual CTC (LPA)', min_value=Decimal('0.01'), max_value=10000, max_digits=10, decimal_places=2, required=False)
    stipend = forms.DecimalField(label='Internship stipend (INR)', min_value=0, max_value=10000000, max_digits=12, decimal_places=2, required=False)
    courses = forms.MultipleChoiceField(choices=COURSES, widget=forms.CheckboxSelectMultiple)
    min_score = forms.DecimalField(min_value=0,max_value=10, required=False, decimal_places=2,max_digits=4)
    class Meta:
        model = Drive
        fields = ['company','title','offer_type','ctc','stipend','stipend_period','courses','min_score','scheduled_at','closes_at','open']
        widgets = {'scheduled_at':forms.DateTimeInput(attrs={'type':'datetime-local'}), 'closes_at':forms.DateTimeInput(attrs={'type':'datetime-local'})}
    def clean(self):
        data = super().clean()
        if data.get('stipend') is not None and not data.get('stipend_period'): self.add_error('stipend_period','Select a payment period.')
        if data.get('closes_at') and data.get('scheduled_at') and data['closes_at'] > data['scheduled_at']:
            self.add_error('closes_at','Applications must close before the drive starts.')
        for field in ('ctc','stipend'): data[field] = str(data[field]) if data.get(field) is not None else ''
        return data

class OfferForm(StrictFormMixin, forms.ModelForm):
    ctc = forms.DecimalField(label='Annual CTC (LPA)', min_value=Decimal('0.01'), max_value=10000, max_digits=10, decimal_places=2, required=False)
    stipend = forms.DecimalField(label='Internship stipend (INR)', min_value=0, max_value=10000000, max_digits=12, decimal_places=2, required=False)
    class Meta:
        model = Offer
        fields = ['company','drive','offer_type','ctc','stipend','stipend_period','issued_at','company_deadline','off_campus','remarks']
        widgets = {'issued_at':forms.DateTimeInput(attrs={'type':'datetime-local'}),'company_deadline':forms.DateTimeInput(attrs={'type':'datetime-local'}),'remarks':forms.Textarea(attrs={'rows':3})}
    def clean(self):
        data = super().clean()
        if data.get('offer_type') != 'I' and data.get('ctc') is None: self.add_error('ctc','Annual CTC is required.')
        if data.get('offer_type') == 'I' and data.get('ctc') is not None: self.add_error('ctc','Do not put an internship stipend in annual CTC.')
        if data.get('stipend') is not None and not data.get('stipend_period'): self.add_error('stipend_period','Select a payment period.')
        drive = data.get('drive')
        if drive and (data.get('company') != drive.company or data.get('offer_type') != drive.offer_type):
            raise ValidationError('Company and offer type must match the selected drive.')
        if drive and data.get('off_campus'): raise ValidationError('Off-campus offers cannot be associated with a campus drive.')
        if not drive and not data.get('off_campus'): raise ValidationError('A drive or an off-campus designation is required.')
        if data.get('company_deadline') and data.get('issued_at') and data['company_deadline'] <= data['issued_at']:
            self.add_error('company_deadline','Deadline must be after issuance.')
        for field in ('ctc','stipend'): data[field] = str(data[field]) if data.get(field) is not None else ''
        return data

class ReasonForm(StrictFormMixin, forms.Form):
    reason = forms.CharField(min_length=10,max_length=2000,widget=forms.Textarea(attrs={'rows':3}))

class MFAForm(StrictFormMixin, forms.Form):
    code = forms.RegexField(r'^\d{6}$', label='Authenticator code', widget=forms.TextInput(attrs={'autocomplete':'one-time-code','inputmode':'numeric'}))

class ReviewForm(StrictFormMixin, forms.Form):
    kind = forms.ChoiceField(choices=[('correction','Profile correction'),('joining','Joining / NOC update'),('policy','Policy review')])
    details = forms.CharField(min_length=10,max_length=2000, widget=forms.Textarea(attrs={'rows':4}))

class AttendanceForm(StrictFormMixin, forms.Form):
    drive = forms.ModelChoiceField(queryset=Drive.objects.all())
    activity = forms.ChoiceField(choices=[(x,x) for x in ['Pre-placement talk','Presentation','Test','Interview','Other']])
    present = forms.BooleanField(required=False)

class OfferUpdateForm(StrictFormMixin, forms.ModelForm):
    reason = forms.CharField(min_length=10, max_length=2000)
    class Meta:
        model = Offer
        fields = ['ppo','joining','noc','withdrawn']

class InviteForm(StrictFormMixin, forms.Form):
    email = forms.EmailField()
    role = forms.ChoiceField(choices=[('officer','Placement officer'),('coordinator','Course coordinator'),('recruiter','Recruiter'),('admin','Administrator')])
    courses = forms.MultipleChoiceField(choices=COURSES, required=False,widget=forms.CheckboxSelectMultiple)
    company = forms.ModelChoiceField(queryset=Company.objects.all(),required=False)
    def clean(self):
        data = super().clean()
        if data.get('role')=='coordinator' and not data.get('courses'): self.add_error('courses','Assign at least one course.')
        if data.get('role')=='recruiter' and not data.get('company'): self.add_error('company','Assign a company.')
        return data
