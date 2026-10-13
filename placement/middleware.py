import time
from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect

class SessionGuard:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        if request.user.is_authenticated:
            now = time.time()
            if (now-request.session.get('last_activity',0)>settings.SESSION_IDLE_SECONDS or
                now-request.session.get('started',0)>settings.SESSION_ABSOLUTE_SECONDS or
                request.session.get('credential_version') != request.user.credential_version):
                logout(request)
                return redirect('login')
            request.session['last_activity'] = now
            exempt = request.path in {'/mfa/', '/logout/', '/reauth/'}
            if not exempt and ((request.user.role in {'admin','officer','coordinator'} and not request.user.mfa_enabled) or
                               (request.user.mfa_enabled and not request.session.get('mfa_verified'))):
                return redirect('mfa')
        return self.get_response(request)

class SecurityHeaders:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        response = self.get_response(request)
        response['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'; object-src 'none'"
        response['Referrer-Policy'] = 'same-origin'
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if request.user.is_authenticated or request.path in {'/login/','/signup/','/mfa/','/reauth/','/forgot/','/resend/'} or request.path.startswith(('/token/','/reset/','/invite/')):
            response['Cache-Control'] = 'no-store'
        return response
