from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("wagvid_app", "0010_event_city_event_competition_level_and_more")]

    operations = [
        migrations.AddField(
            model_name="mediaasset",
            name="content_type",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="mediaasset",
            name="original_filename",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="mediaasset",
            name="size_bytes",
            field=models.BigIntegerField(
                blank=True, null=True, validators=[MinValueValidator(0)]
            ),
        ),
    ]
