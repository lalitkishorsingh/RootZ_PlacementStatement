from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from .models import Policy, ExceptionGrant

DEFAULT = {'b_min': '6', 'a_min': '10', 'aplus_min': '16', 'b_multiplier': '1.5'}

@dataclass
class Decision:
    outcome: str
    codes: list
    explanations: list
    version: str
    def data(self): return asdict(self)

def amount(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number > 0 else None
    except (InvalidOperation, TypeError): return None

def category(value, config=None):
    config = config or DEFAULT
    number = amount(value)
    if number is None: return None
    if number >= Decimal(config['aplus_min']): return 'A+'
    if number >= Decimal(config['a_min']): return 'A'
    if number >= Decimal(config['b_min']): return 'B'
    return 'C'

def evaluate(student, opportunity, *, exclude_offer=None, check_open=True):
    policy = Policy.objects.filter(active=True).first()
    version = policy.version if policy else 'unconfigured'
    config = policy.config if policy else DEFAULT
    blocked, review = [], []
    def block(code, text): blocked.append((code, text))
    def manual(code, text): review.append((code, text))
    if not policy: manual('NO_POLICY', 'An active policy must be configured.')
    if student.archived: block('ARCHIVED', 'The student record is archived.')
    if student.registration != 'registered': block('REGISTRATION', 'Placement registration is required.')
    if student.eligibility == 'ineligible': block('INELIGIBLE', 'The student is marked ineligible.')
    elif student.eligibility != 'eligible': manual('ELIGIBILITY_PENDING', 'Eligibility requires verification.')
    if check_open and (not opportunity.open or opportunity.closes_at <= timezone.now()):
        block('DRIVE_CLOSED', 'Applications to this drive are closed.')
    if student.course not in opportunity.courses: block('COURSE', 'The programme is not included in this drive.')
    if opportunity.min_score is not None:
        if student.academic_score is None: manual('SCORE_PENDING', 'Academic score needs verification.')
        elif Decimal(str(student.academic_score)) < Decimal(str(opportunity.min_score)): block('SCORE', 'Company academic criteria are not met.')
    if hasattr(opportunity, 'pk') and opportunity.pk and student.sanction_set.filter(active=True, drives=opportunity.pk).exists():
        block('ATTENDANCE_SANCTION', 'An approved attendance sanction covers this drive.')
    new_category = category(opportunity.ctc, config)
    if opportunity.offer_type != 'I' and new_category is None: manual('CTC_PENDING', 'Annual compensation requires verification.')
    selected = student.offers.filter(verified=True, withdrawn=False)
    if exclude_offer: selected = selected.exclude(pk=exclude_offer)
    for offer in selected:
        old_category = category(offer.ctc, config)
        if old_category == 'A+': block('APLUS_EXIT', 'A+ selection ends further placement participation.')
        if offer.offer_type == 'IF' and offer.company_id != opportunity.company_id:
            block('COMBINED_SELECTION', 'An internship + PPO/FTE selection blocks other organizations.')
        if offer.offer_type == opportunity.offer_type and offer.offer_type in {'I','F'}:
            block('SAME_TYPE', 'A previous selection prohibits another opportunity of this offer type.')
        # Category switching is relevant only when both offers contain annual FTE CTC.
        if offer.offer_type != 'I' and opportunity.offer_type != 'I':
            if old_category is None: manual('EXISTING_CTC_PENDING', 'Existing annual compensation requires verification.')
            elif old_category == 'A' and new_category != 'A+': block('A_SWITCH', 'Category A allows switching only to A+.')
            elif old_category == 'B' and (amount(opportunity.ctc) is None or amount(opportunity.ctc) < amount(offer.ctc)*Decimal(config['b_multiplier'])):
                block('B_SWITCH', f'The new annual CTC must be at least {config["b_multiplier"]} times existing CTC.')
            elif old_category == 'C' and new_category not in {'B','A','A+'}:
                block('C_SWITCH', 'Category C requires a higher-category opportunity.')
    if hasattr(opportunity, 'pk') and opportunity.pk and not student.archived:
        grant = ExceptionGrant.objects.filter(student=student, drive=opportunity.pk, revoked=False, expires__gt=timezone.now()).first()
        # Exceptions never bypass archived records, closed drives or missing policy configuration.
        hard = {'ARCHIVED','DRIVE_CLOSED','NO_POLICY'}
        if grant and not any(code in hard for code, _ in blocked + review):
            return Decision('allowed', ['APPROVED_EXCEPTION'], ['Administrator exception: ' + grant.reason], version)
    reasons = list(dict.fromkeys(blocked + review))
    return Decision('blocked' if blocked else 'manual_review' if review else 'allowed',
                    [code for code, _ in reasons] or ['ELIGIBLE'],
                    [text for _, text in reasons] or ['All placement and company criteria are satisfied.'], version)
