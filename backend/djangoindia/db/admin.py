# from django.conf import settings
from import_export import fields, resources
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget

from django.conf import settings
from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count, F
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path

from djangoindia.bg_tasks.event_registration import send_mass_mail_task
from djangoindia.db.models import (
    CommunityPartner,
    ContactUs,
    Event,
    EventRegistration,
    EventUserRegistration,
    SocialLoginConnection,
    Sponsor,
    Sponsorship,
    Subscriber,
    Update,
    User,
    Volunteer,
)

from .forms import EmailForm, EventForm, UpdateForm


@admin.action(description="Send email to selected users")
def send_email_to_selected_users(modeladmin, request, queryset):
    ids = queryset.values_list("id", flat=True)
    return redirect(f'send_email/?ids={",".join(map(str, ids))}')


class SponsorInline(admin.TabularInline):
    model = Sponsorship
    extra = 1


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "start_date", "event_mode", "created_at")
    readonly_fields = ("created_at", "updated_at", "slug")
    search_fields = ["name", "city"]
    form = EventForm
    inlines = [SponsorInline]
    filter_horizontal = ("volunteers",)


class EventRegistrationResource(resources.ModelResource):
    class Meta:
        model = EventRegistration


@admin.register(EventRegistration)
class EventRegistrationAdmin(ImportExportModelAdmin):
    list_display = (
        "event",
        "first_name",
        "email",
        "created_at",
        "attendee_type",
        "first_time_attendee",
    )
    readonly_fields = ("created_at", "updated_at", "first_time_attendee")
    list_filter = ("event__name", "attendee_type", "first_time_attendee")
    search_fields = [
        "email",
        "event__name",
        "first_name",
        "last_name",
        "first_time_attendee",
        "attendee_type",
    ]
    raw_id_fields = ("event",)
    actions = [send_email_to_selected_users]
    resource_class = EventRegistrationResource

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "send_email/",
                self.admin_site.admin_view(self.send_email_view),
                name="send_email",
            ),
        ]
        return custom_urls + urls

    @transaction.atomic
    def delete_model(self, request, obj):
        if obj.event.seats_left < obj.event.max_seats:
            obj.event.seats_left += 1
            obj.event.save()
        super().delete_model(request, obj)

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        # Group registrations by event and count them
        event_counts = queryset.values("event").annotate(count=Count("id"))

        # Update seats_left for each affected event
        for event_count in event_counts:
            Event.objects.filter(id=event_count["event"]).update(
                seats_left=F("seats_left") + event_count["count"]
            )

        # Perform the actual deletion
        super().delete_queryset(request, queryset)

    def send_email_view(self, request):
        if request.method == "POST":
            form = EmailForm(request.POST)
            if form.is_valid():
                try:
                    subject = form.cleaned_data["subject"]
                    message = form.cleaned_data["message"]
                    emails = []
                    from_email = settings.DEFAULT_FROM_EMAIL

                    registration_ids = request.GET.get("ids").split(",")
                    queryset = EventRegistration.objects.filter(id__in=registration_ids)

                    for registration in queryset:
                        recipient_email = registration.email
                        emails.append((subject, message, from_email, [recipient_email]))

                    send_mass_mail_task.delay(emails, fail_silently=False)
                    messages.success(
                        request, f"{len(emails)} emails sent successfully."
                    )
                    return redirect("../")
                except Exception as e:
                    messages.error(request, f"Error sending emails: {str(e)}")
        else:
            form = EmailForm()

        context = {
            "form": form,
            "opts": self.model._meta,
            "queryset": request.GET.get("ids").split(","),
        }
        return TemplateResponse(request, "admin/send_email.html", context)


@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "created_at")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
    search_fields = [
        "name",
        "email",
    ]


@admin.register(ContactUs)
class ContactUsAdmin(admin.ModelAdmin):
    list_display = ("first_name", "email", "created_at")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
    search_fields = [
        "email",
    ]


class SponsorshipResource(resources.ModelResource):
    sponsor_name = fields.Field(
        column_name="sponsor_name",
        attribute="sponsor_details",
        widget=ForeignKeyWidget(Sponsor, "name"),
    )
    sponsor_email = fields.Field(
        column_name="sponsor_email", attribute="sponsor_details__email"
    )
    sponsor_url = fields.Field(
        column_name="sponsor_url", attribute="sponsor_details__url"
    )

    class Meta:
        model = Sponsorship
        fields = (
            "id",
            "sponsor_name",
            "sponsor_email",
            "sponsor_url",
            "tier",
            "type",
            "amount_inr",
            "created_at",
            "updated_at",
        )
        export_order = fields


@admin.register(Sponsorship)
class SponsorshipAdmin(ImportExportModelAdmin):
    list_display = ("sponsor_details", "tier", "type", "event")
    list_filter = ("type", "event", "tier")
    search_fields = [
        "sponsor_details__name",
    ]
    readonly_fields = ("created_at", "updated_at")
    resource_class = SponsorshipResource

    def get_export_queryset(self, request):
        return super().get_export_queryset(request).select_related("sponsor_details")


@admin.register(Sponsor)
class SponsorAdmin(admin.ModelAdmin):
    list_display = ["name", "type", "email"]
    search_fields = [
        "name",
    ]
    readonly_fields = ("created_at", "updated_at")


# email sending functionality and update registration
@admin.register(Update)
class UpdateAdmin(admin.ModelAdmin):
    form = UpdateForm
    list_display = ("email_subject", "type", "created_at", "mail_sent")
    search_fields = ["email_subject", "type"]
    readonly_fields = ("created_at", "updated_at")
    actions = ["send_update"]

    @admin.action(description="Send selected updates to subscribers")
    def send_update(self, request, queryset):
        for update in queryset:
            update.send_bulk_emails()
        self.message_user(request, "Update emails sent.")


@admin.register(CommunityPartner)
class CommunityPartnerAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "website",
        "contact_name",
        "contact_email",
        "contact_number",
        "description",
    ]
    search_fields = ["name"]
    readonly_fields = ("created_at", "updated_at")


class EventVolunteerResource(resources.ModelResource):
    class Meta:
        model = Volunteer
        fields = ("id", "name", "about", "email", "twitter", " linkedin")


@admin.register(Volunteer)
class EventVolunteerAdmin(ImportExportModelAdmin):
    list_display = ["name", "about", "email"]
    search_fields = ["events__name", "name", "email"]
    readonly_fields = ("created_at", "updated_at")
    list_filter = ("events__name",)
    resource_class = EventVolunteerResource
    filter_horizontal = ("events",)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "is_superuser",
        "is_email_verified",
    )
    list_filter = (
        "is_active",
        "is_staff",
        "is_superuser",
        "is_email_verified",
        "gender",
    )
    search_fields = ("username", "email", "first_name", "last_name")
    readonly_fields = ("created_at", "updated_at")
    filter_horizontal = (
        "groups",
        "user_permissions",
    )
    fieldsets = (
        (None, {"fields": ("username", "email", "password")}),
        (
            "Personal info",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "avatar",
                    "cover_image",
                    "gender",
                    "mobile_number",
                    "bio",
                    "about",
                    "website",
                    "linkedin",
                    "github",
                    "twitter",
                    "instagram",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                    "is_email_verified",
                    "is_password_expired",
                    "is_onboarded",
                ),
            },
        ),
        ("Important dates", {"fields": ("created_at", "updated_at")}),
    )
    ordering = ("-created_at",)


@admin.register(SocialLoginConnection)
class SocialLoginConnectionAdmin(admin.ModelAdmin):
    list_display = ["user", "provider", "created_at"]
    search_fields = ["user__username", "user__email"]
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)

    def provider(self, obj):
        return obj.medium


@admin.register(EventUserRegistration)
class EventUserRegistrationAdmin(admin.ModelAdmin):
    list_display = ["user", "event", "created_at"]
    search_fields = ["user__username", "user__email", "event__name"]
    readonly_fields = ("created_at", "updated_at")
    list_filter = ("event__name",)
    ordering = ("-created_at",)
