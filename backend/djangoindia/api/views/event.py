from django.db.models import Prefetch
from django.utils import timezone
from djangoindia.api.serializers.event import (
    EventLiteSerializer,
    EventRegistrationSerializer,
    EventSerializer,
)
from djangoindia.bg_tasks.event_registration import registration_confirmation_email_task
from djangoindia.constants import POST
from djangoindia.db.models import (
    CommunityPartner,
    Event,
    EventRegistration,
    Sponsorship,
    Volunteer,
)
from rest_framework import status, viewsets
from rest_framework.response import Response


# Create your views here.
class EventAPIView(viewsets.ModelViewSet):
    lookup_field = "slug"
    queryset = (
        Event.objects.all()
        .prefetch_related(
            Prefetch(
                "sponsors",
                queryset=Sponsorship.objects.filter(type="event_sponsorship")
                .select_related("sponsor_details")
                .only(
                    "tier",
                    "type",
                    "sponsor_details__url",
                    "sponsor_details__name",
                    "sponsor_details__type",
                    "sponsor_details__logo",
                ),
                to_attr="event_sponsors",
            ),
            Prefetch(
                "volunteers",
                queryset=Volunteer.objects.only(
                    "name", "photo", "about", "email", "twitter", "linkedin"
                ),
                to_attr="event_volunteers",
            ),
        )
        .order_by("-created_at")
    )

    def get_serializer_class(self):
        if self.request.method == POST:
            return EventRegistrationSerializer
        return EventLiteSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        all_community_partners = CommunityPartner.objects.all()
        serializer = self.get_serializer(
            queryset,
            many=True,
            context={"all_community_partners": all_community_partners},
        )
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        # Only fetch partners who were created before the event
        all_community_partners = CommunityPartner.objects.filter(
            created_at__lte=instance.created_at
        )
        serializer = EventSerializer(
            instance, context={"all_community_partners": all_community_partners}
        )
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):
        try:
            event_id = request.data.get("event")
            email = request.data.get("email")

            event = self.get_event(event_id)
            self._validate_event_registration(event)
            self._check_existing_registration(email, event_id)

            self.create(request, *args, **kwargs)
            self._send_confirmation_email(email, event_id)

            return Response(
                {
                    "message": (
                        "You're in! We've sent a shiny email to your inbox. "
                        "Time to celebrate!"
                    )
                },
                status=status.HTTP_201_CREATED,
            )
        except ValidationError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ConflictError as e:
            return Response({"message": str(e)}, status=status.HTTP_409_CONFLICT)
        except Exception:
            return Response(
                {"message": "An unexpected error occurred."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def get_event(self, event_id):
        try:
            return Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            raise ValidationError("Event not found.")

    def _validate_event_registration(self, event):
        if event.registration_end_date <= timezone.now():
            raise ValidationError("Registration has already ended for this event.")
        if event.seats_left is None:
            raise ValidationError("Registration hasn't started yet.")
        if event.seats_left < 1:
            raise ValidationError(
                "Unfortunately, there are no more seats left for the event."
            )

    def _check_existing_registration(self, email, event_id):
        if EventRegistration.objects.filter(email=email, event=event_id).exists():
            raise ConflictError(
                "We get it, you're excited. But you've already secured your ticket!"
            )

    def _send_confirmation_email(self, email, event_id):
        registration_confirmation_email_task.delay(email, event_id)


class ValidationError(Exception):
    pass


class ConflictError(Exception):
    pass
