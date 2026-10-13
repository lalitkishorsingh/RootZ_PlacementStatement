import hashlib
import hmac
import json
import logging
from django.conf import settings
from django.db import transaction
from .models import AuditEvent, AuditHead

def signature(previous, actor, action, target, details, occurred_at):
    payload = json.dumps([previous, str(actor), action, str(target), details, occurred_at.isoformat()],
                         sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hmac.new(settings.AUDIT_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()

@transaction.atomic
def record(actor, action, target='', details=None):
    # Row 1 is created by migration. Lock serializes the entire chain on PostgreSQL.
    head = AuditHead.objects.select_for_update().get(pk=1)
    event = AuditEvent(actor_id_ref=str(actor.pk) if actor else 'anonymous', action=action,
                       target=str(target), details=details or {}, previous=head.digest)
    event.digest = signature(event.previous, event.actor_id_ref, action, event.target, event.details, event.occurred_at)
    event.save(force_insert=True)
    head.digest = event.digest
    head.save(update_fields=['digest'])
    return event

def verify():
    previous = '0' * 64
    for event in AuditEvent.objects.order_by('id').iterator():
        expected = signature(previous, event.actor_id_ref, event.action, event.target, event.details, event.occurred_at)
        if event.previous != previous or not hmac.compare_digest(event.digest, expected):
            logging.getLogger('placement.security').critical('Audit integrity failure at event %s', event.pk)
            return False
        previous = event.digest
    return hmac.compare_digest(previous, AuditHead.objects.get(pk=1).digest)
