from django.urls import path
from placement import views as v, auth_views as a

urlpatterns = [
    path('',v.dashboard,name='dashboard'),path('login/',a.login,name='login'),path('logout/',a.logout,name='logout'),
    path('signup/',a.signup,name='signup'),path('token/<str:raw>/',a.token,name='token'),path('forgot/',a.forgot,name='forgot'),
    path('reset/<str:raw>/',a.reset,name='reset'),path('mfa/',a.mfa,name='mfa'),path('reauth/',a.reauth,name='reauth'),
    path('resend/',a.resend,name='resend'),
    path('students/',v.students,name='students'),path('students/new/',v.student_edit,name='student_create'),
    path('students/<uuid:pk>/',v.student_detail,name='student'),path('students/<uuid:pk>/edit/',v.student_edit,name='student_edit'),
    path('students/<uuid:pk>/archive/',v.archive,name='archive'),path('students/<uuid:pk>/offers/new/',v.offer_create,name='offer_create'),
    path('students/<uuid:pk>/review/',v.review_create,name='review_create'),path('students/<uuid:pk>/attendance/',v.attendance,name='attendance'),
    path('students/<uuid:pk>/exception/<int:drive_pk>/',v.exception,name='exception'),
    path('companies/',v.companies,name='companies'),path('companies/new/',v.company_create,name='company_create'),
    path('drives/',v.drives,name='drives'),path('drives/new/',v.drive_edit,name='drive_create'),path('drives/<int:pk>/edit/',v.drive_edit,name='drive_edit'),
    path('drives/<int:pk>/apply/',v.apply,name='apply'),path('applications/',v.applications,name='applications'),
    path('applications/<int:pk>/review/',v.application_review,name='application_review'),
    path('offers/',v.offers,name='offers'),path('offers/<uuid:pk>/action/',v.offer_action,name='offer_action'),
    path('offers/<uuid:pk>/update/',v.offer_update,name='offer_update'),
    path('reviews/',v.reviews,name='reviews'),path('reviews/<int:pk>/resolve/',v.review_resolve,name='review_resolve'),
    path('accounts/',v.accounts,name='accounts'),path('accounts/invite/',a.invite,name='invite'),
    path('accounts/<int:pk>/approve/',v.approve_signup,name='approve_signup'),path('accounts/<int:pk>/edit/',v.account_edit,name='account_edit'),
    path('policy/',v.policy_settings,name='policy'),path('audit/',v.audit_log,name='audit'),path('export/',v.export,name='export'),
    path('reports/',v.reports,name='reports'),
    path('import/',v.import_records,name='import'),path('import/<int:pk>/',v.import_preview,name='import_preview'),path('health/',v.health,name='health'),
]
