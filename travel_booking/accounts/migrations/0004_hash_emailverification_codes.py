import hashlib

from django.db import migrations, models


def hash_existing_verification_codes(apps, schema_editor):
    EmailVerification = apps.get_model('accounts', 'EmailVerification')

    for verification in EmailVerification.objects.all().iterator():
        code = verification.code or ''
        if len(code) == 64:
            try:
                int(code, 16)
                continue
            except ValueError:
                pass

        verification.code = hashlib.sha256(code.encode('utf-8')).hexdigest()
        verification.save(update_fields=['code'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_emailverification'),
    ]

    operations = [
        migrations.AlterField(
            model_name='emailverification',
            name='code',
            field=models.CharField(db_index=True, max_length=64),
        ),
        migrations.RunPython(hash_existing_verification_codes, migrations.RunPython.noop),
    ]
