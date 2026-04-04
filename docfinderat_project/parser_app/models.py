from django.db import models


class Doctor(models.Model):
    name = models.CharField(max_length=500)
    profile_url = models.URLField(max_length=2000)
    search_slug = models.CharField(max_length=200, default="")
    rating = models.CharField(max_length=10, null=True, blank=True)
    reviews = models.PositiveIntegerField(null=True, blank=True)
    specialty = models.CharField(max_length=500, null=True, blank=True)
    address = models.CharField(max_length=512, null=True, blank=True)
    services = models.TextField(null=True, blank=True)
    photo_url = models.URLField(max_length=2000, null=True, blank=True)
    appointment_url = models.URLField(max_length=2000, null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    fax = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    website = models.URLField(max_length=2000, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    address_full = models.CharField(max_length=500, null=True, blank=True)
    zip_code = models.CharField(max_length=20, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    opening_hours = models.JSONField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    photo_url_full = models.URLField(max_length=2000, null=True, blank=True)

    class Meta:
        db_table = "doctors"
        unique_together = [["profile_url", "search_slug"]]

    def __str__(self):
        return self.name


class DoctorGallery(models.Model):
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="gallery")
    photo_url = models.URLField(max_length=2000)

    class Meta:
        db_table = "doctor_gallery"

    def __str__(self):
        return f"{self.doctor.name} — {self.photo_url}"
