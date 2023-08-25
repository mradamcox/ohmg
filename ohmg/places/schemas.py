from typing import List, Optional

from django.urls import reverse
from ninja import (
    Schema,
    Field
)

from ohmg.loc_insurancemaps.models import Volume

class PlaceSchema(Schema):
    """ very lightweight serialization of a Place with its Items"""

    name: str = Field(..., alias="__str__")
    items: list
    url: str

    @staticmethod
    def resolve_items(obj):
        values = Volume.objects.filter(locales__id__exact=obj.id) \
            .order_by('year') \
            .values('identifier', 'year', 'volume_no')
        for i in values:
            i['url'] = reverse('volume_summary', args=(i['identifier'], ))
        return values

    @staticmethod
    def resolve_url(obj):
        return reverse('viewer', args=(obj.slug, ))
