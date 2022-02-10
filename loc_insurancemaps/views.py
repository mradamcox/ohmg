import os
import json
import logging

from django.shortcuts import render, get_object_or_404
from django.views import View
from django.urls import reverse
from django.http import JsonResponse
from django.middleware import csrf

from geonode.base.models import Region
from geonode.layers.models import Layer
from geonode.groups.conf import settings as groups_settings

from .models import Volume
from .utils import unsanitize_name, filter_volumes_for_use
from .enumerations import STATE_CHOICES
from .api import CollectionConnection
from .tasks import import_sheets_as_task

logger = logging.getLogger(__name__)


def get_user_type(user):
    if user.is_superuser:
        user_type = "superuser"
    elif user.groups.filter(name=groups_settings.REGISTERED_MEMBERS_GROUP_NAME).exists():
        user_type = "participant"
    else:
        user_type = "anonymous"
    return user_type


class HomePage(View):

    def get(self, request):

        lc = CollectionConnection(delay=0, verbose=True)
        city_list = lc.get_city_list_by_state("louisiana")
        context_dict = {
            "svelte_params": {
                "STATE_CHOICES": STATE_CHOICES,
                "CITY_QUERY_URL": reverse('lc_api'),
                'USER_TYPE': get_user_type(request.user),
                'CITY_LIST': city_list,
            }
        }

        return render(
            request,
            "site_index.html",
            context=context_dict
        )

class Volumes(View):

    def get(self, request):

        started_volumes = Volume.objects.filter(status="started").order_by("city", "year")
        lc = CollectionConnection(delay=0, verbose=True)
        city_list = lc.get_city_list_by_state("louisiana")

        volumes_values = started_volumes.values_list(
            "identifier",
            "city",
            "county_equivalent",
            "state",
            "year",
            "sheet_ct",
            "volume_no",
            "loaded_by__username",
        )
        loaded_volumes = []
        for v in volumes_values:
            title = f"{v[1]}, {v[2]}, {v[4]}"
            if v[6] is not None:
                title += f", Vol. {v[6]}"
            # if v[6] is not None:
            #     title = f"{v[1]}, {v[2]}, {v[4]}, Vol. {v[6]}"
            loaded_volumes.append({
                "identifier": v[0],
                "city": v[1],
                "county_equivalent": v[2],
                "state": v[3],
                "year": v[4],
                "sheet_ct": v[5],
                "volume_no": v[6],
                "loaded_by": {
                    "name": v[7],
                    "profile": reverse("profile_detail", args=(v[7], )),
                },
                "title": title,
                "urls": {
                    "summary": reverse("volume_summary", args=(v[0],))
                }
            })

        context_dict = {
            "svelte_params": {
                "STARTED_VOLUMES": loaded_volumes,
                "STATE_CHOICES": STATE_CHOICES,
                "CITY_QUERY_URL": reverse('lc_api'),
                'USER_TYPE': get_user_type(request.user),
                'CITY_LIST': city_list,
            }
        }
        return render(
            request,
            "lc/volumes.html",
            context=context_dict
        )

class VolumeDetail(View):

    def get(self, request, volumeid):

        volume = get_object_or_404(Volume, pk=volumeid)
        volume_json = volume.serialize()

        gs = os.getenv("GEOSERVER_LOCATION", "http://localhost:8080/geoserver/")
        gs = gs.rstrip("/") + "/"
        geoserver_ows = f"{gs}ows/"

        context_dict = {
            "svelte_params": {
                "VOLUME": volume_json,
                "CSRFTOKEN": csrf.get_token(request),
                'USER_TYPE': get_user_type(request.user),
                'GEOSERVER_WMS': geoserver_ows,
            }
        }
        return render(
            request,
            "lc/volume_summary.html",
            context=context_dict
        )

    def post(self, request, volumeid):

        body = json.loads(request.body)
        operation = body.get("operation", None)

        if operation == "initialize":
            import_sheets_as_task.apply_async(
                (volumeid, request.user.pk),
                queue="update"
            )
            volume = Volume.objects.get(pk=volumeid)
            volume_json = volume.serialize()

            # set a few things manually here that may not be set on the Volume
            # yet due to async operations
            volume_json["loaded_by"] = {
                "name": request.user.username,
                "profile": reverse("profile_detail", args=(request.user.username, )),
            }
            volume_json["status"] = "initializing..."

            return JsonResponse(volume_json)

        elif operation == "set-index-layers":

            volume = Volume.objects.get(pk=volumeid)

            index_layers = body.get("indexLayerIds", [])
            volume.ordered_layers["index_layers"] = index_layers
            # remove index layers from main layer list
            volume.ordered_layers["layers"] = [i for i in volume.ordered_layers['layers'] if not i in index_layers]
            volume.save(update_fields=["ordered_layers"])

            volume_json = volume.serialize()
            return JsonResponse(volume_json)

        elif operation == "set-layer-order":

            volume = Volume.objects.get(pk=volumeid)
            volume.ordered_layers["layers"] = body.get("layerIds", [])
            volume.ordered_layers["index_layers"] = body.get("indexLayerIds", [])
            volume.save(update_fields=["ordered_layers"])

            volume_json = volume.serialize()
            return JsonResponse(volume_json)

        elif operation == "refresh":
            volume = Volume.objects.get(pk=volumeid)
            volume_json = volume.serialize()
            return JsonResponse(volume_json)

class SimpleAPI(View):

    def get(self, request):
        qtype = request.GET.get("t", None)
        state = request.GET.get("s", None)
        city = request.GET.get("c", None)

        lc = CollectionConnection(delay=0, verbose=True)

        ## returns a list of all cities with volumes in this state
        if qtype == "cities":
            city_list = lc.get_city_list_by_state(state)
            missing = []
            for i in city_list:
                try:
                    reg = Region.objects.get(name__iexact=i[0])
                except Region.DoesNotExist:
                    missing.append(i)

            return JsonResponse(city_list, safe=False)

        ## return a list of all volumes in a city
        elif qtype == "volumes":

            city = unsanitize_name(state, city)
            volumes = lc.get_volume_list_by_city(city, state)

            ## a little bit of post-processing on the volume list
            volumes = filter_volumes_for_use(volumes)

            return JsonResponse(volumes, safe=False)
        
        else:
            return JsonResponse({})