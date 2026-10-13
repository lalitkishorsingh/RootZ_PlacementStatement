from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from placement.models import Offer, Student, Token, ImportBatch, Throttle
from placement import audit

class Command(BaseCommand):
    help = 'Expire pending verified offers and prune short-lived secrets; schedule every minute.'
    def handle(self,*args,**options):
        count = 0
        for pk in Offer.objects.filter(verified=True,acceptance='pending',deadline__lte=timezone.now()).values_list('pk',flat=True):
            with transaction.atomic():
                student_id = Offer.objects.values_list('student_id',flat=True).get(pk=pk)
                Student.objects.select_for_update().get(pk=student_id)
                item = Offer.objects.select_for_update().get(pk=pk)
                if item.acceptance=='pending' and item.deadline<=timezone.now():
                    item.acceptance='expired'; item.save(update_fields=['acceptance'])
                    audit.record(None,'offer.expire',pk); count += 1
        Token.objects.filter(expires__lte=timezone.now()).delete()
        from datetime import timedelta
        ImportBatch.objects.filter(created_at__lt=timezone.now()-timedelta(hours=1)).delete()
        Throttle.objects.filter(window__lt=timezone.now()-timedelta(days=1)).delete()
        self.stdout.write(f'{count} offers expired.')
