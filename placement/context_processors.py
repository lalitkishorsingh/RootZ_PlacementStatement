def security_state(request):
    user = request.user
    locked = user.is_authenticated and (
        (user.role in {'admin', 'officer', 'coordinator'} and not user.mfa_enabled)
        or (user.mfa_enabled and not request.session.get('mfa_verified'))
    )
    page = request.resolver_match.url_name if request.resolver_match else ''
    sections = {
        'student': 'students', 'student_create': 'students', 'student_edit': 'students',
        'archive': 'students', 'attendance': 'students', 'exception': 'students',
        'drive_create': 'drives', 'drive_edit': 'drives', 'apply': 'drives',
        'application_review': 'applications', 'offer_create': 'offers', 'offer_action': 'offers',
        'offer_update': 'offers', 'review_create': 'reviews', 'review_resolve': 'reviews',
        'company_create': 'companies', 'invite': 'accounts', 'approve_signup': 'accounts',
        'account_edit': 'accounts', 'import_preview': 'import',
    }
    return {'navigation_locked': locked, 'active_nav': sections.get(page, page)}
