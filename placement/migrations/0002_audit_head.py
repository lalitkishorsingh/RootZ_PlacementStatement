from django.db import migrations

def initialize(apps,schema_editor):
    apps.get_model('placement','AuditHead').objects.get_or_create(pk=1)

class Migration(migrations.Migration):
    dependencies = [('placement','0001_initial')]
    operations = [migrations.RunPython(initialize,migrations.RunPython.noop)]
