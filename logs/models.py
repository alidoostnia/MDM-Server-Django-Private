from django.db import models

class FakeDeviceLogsModel(models.Model):
    class Meta:
        managed = False  # no database table
        verbose_name = "Device Logs (MongoDB)"
        verbose_name_plural = "Device Logs (MongoDB)"