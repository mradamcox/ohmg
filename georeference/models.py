import os
import uuid
import json
from osgeo import gdal, osr
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.gis.geos import Point
from django.contrib.gis.db import models
from django.contrib.postgres.fields import JSONField
from django.core.files import File
from django.db.models import signals

from geonode.documents.models import Document, DocumentResourceLink
from geonode.layers.models import Layer, Style
from geonode.layers.utils import file_upload
from geonode.thumbs.thumbnails import create_thumbnail
from geonode.geoserver.helpers import save_style

from .georeferencer import Georeferencer
from .splitter import Splitter
from .utils import (
    get_gs_catalog,
    full_reverse,
    TKeywordManager,
)

logger = logging.getLogger(__name__)

class SplitDocumentLink(DocumentResourceLink):
    """
    Inherits from the DocumentResourceLink in GeoNode. This allows
    new instances of this model to be used by GeoNode in a default
    manner, while this app can use them in its own way.
    
    Used to create a link between split documents and their children.
    """

    class Meta:
        verbose_name = "Split Document Link"
        verbose_name_plural = "Split Document Links"

    def __str__(self):
        child = Document.objects.get(pk=self.object_id)
        return f"{self.document.__str__()} --> {child.__str__()}"

class GeoreferencedDocumentLink(DocumentResourceLink):
    """
    Inherits from the DocumentResourceLink in GeoNode. This allows
    new instances of this model to be used by GeoNode in a default
    manner, while this app can use them in its own way.

    Used to create a link between georeferenced documents and the
    resulting layer.
    """

    class Meta:
        verbose_name = "Georeferenced Document Link"
        verbose_name_plural = "Georeferenced Document Links"

    def __str__(self):
        try:
            layer_name = Layer.objects.get(pk=self.object_id).alternate
        except Layer.DoesNotExist:
            layer_name = "None"
        return f"{self.document.__str__()} --> {layer_name}"

class SplitEvaluation(models.Model):

    class Meta:
        verbose_name = "Split Evaluation"
        verbose_name_plural = "Split Evaluations"

    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    split_needed = models.BooleanField(default=None, null=True, blank=True)
    cutlines = JSONField(default=None, null=True, blank=True)
    divisions = JSONField(default=None, null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.CASCADE)
    created = models.DateTimeField(
        auto_now_add=True,
        null=False,
        blank=False)

    def __str__(self):
        return f"{self.document.__str__()} - {self.user} - {self.created}"

    @property
    def georeferenced_downstream(self):
        """Returns True if the related document or its children (if it
        has been split) have already been georeferenced."""

        if self.split_needed is True:
            docs_to_check = self.get_children()
        else:
            docs_to_check = [self.document]

        tkm = TKeywordManager()
        return any([tkm.is_georeferenced(d) for d in docs_to_check])

    def get_children(self):
        """Returns a list of all the child documents created by this
        determination."""

        ct = ContentType.objects.get(app_label="documents", model="document")
        child_ids = SplitDocumentLink.objects.filter(
            document=self.document,
            content_type=ct,
        ).values_list("object_id", flat=True)
        return list(Document.objects.filter(pk__in=child_ids))

    def preview_divisions(self):

        if self.cutlines is None:
            return []

        s = Splitter(image_file=self.document.doc_file.path)
        return s.generate_divisions(self.cutlines)

    def run(self):
        """
        Runs the document split process based on prestored segmentation info
        that has been generated for this document. New Documents are made for
        each child image, SplitDocumentLinks are created to link this parent
        Document with its children. The parent document is also marked as
        metadata_only so that it no longer shows up in the search page lists.
        """

        tkm = TKeywordManager()
        tkm.set_status(self.document, "splitting")

        if self.split_needed is False:
            tkm.set_status(self.document, "prepared")
            self.document.metadata_only = False
            self.document.save()
        else:
            s = Splitter(image_file=self.document.doc_file.path)
            s.generate_divisions(self.cutlines)
            new_images = s.split_image()

            for n, file_path in enumerate(new_images, start=1):

                fname = os.path.basename(file_path)
                new_doc = Document.objects.get(pk=self.document.pk)
                new_doc.pk = None
                new_doc.id = None
                new_doc.uuid = None
                new_doc.thumbnail_url = None
                new_doc.metadata_only = False
                new_doc.title = f"{self.document.title} [{n}]"
                with open(file_path, "rb") as openf:
                    new_doc.doc_file.save(fname, File(openf))
                new_doc.save()

                os.remove(file_path)

                ct = ContentType.objects.get(app_label="documents", model="document")
                SplitDocumentLink.objects.create(
                    document=self.document,
                    content_type=ct,
                    object_id=new_doc.pk,
                )

                for r in self.document.regions.all():
                    new_doc.regions.add(r)
                tkm.set_status(new_doc, "prepared")

            if len(new_images) > 1:
                self.document.metadata_only = True
                self.document.save()

            tkm.set_status(self.document, "split")

        return

    def cleanup(self):
        """Method called with pre_delete signal that cleans up resulting
        documents from previous split operations, if necessary. This is
        meant to provide a "reset" capability for SplitDeterminations."""

        # first check to make sure this determination can be reversed.
        if self.georeferenced_downstream is True:
            logger.warn(f"Removing SplitEvaluation {self.pk} even though downstream georeferencing has occurred.")

        # if a split was made, remove all descendant documents before deleting
        if self.split_needed is True:
            for child in self.get_children():
                child.delete()

        SplitDocumentLink.objects.filter(document=self.document).delete()

        TKeywordManager().set_status(self.document, "unprepared")
        self.document.metadata_only = False
        self.document.save()

    def serialize(self):
        return {
            "allow_reset": not self.georeferenced_downstream,
            "user": {
                "name": self.user.username,
                "profile": full_reverse("profile_detail", args=(self.user.username, )),
            },
            "date": (self.created.month, self.created.day, self.created.year),
            "date_str": self.created.strftime("%Y-%m-%d"),
            "datetime": self.created.strftime("%Y-%m-%d - %H:%M"),
            "split_needed": self.split_needed,
            "divisions_ct": len(self.get_children()),
        }

def pre_delete_split_evaluation(instance, sender, **kwargs):
    instance.cleanup()

signals.pre_delete.connect(pre_delete_split_evaluation, sender=SplitEvaluation)


class GeoreferenceSession(models.Model):

    class Meta:
        verbose_name = "Georeference Session"
        verbose_name_plural = "Georeference Sessions"

    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    layer = models.ForeignKey(Layer, models.SET_NULL, null=True, blank=True)
    gcps_used = JSONField(null=True, blank=True)
    transformation_used = models.CharField(null=True, blank=True, max_length=20)
    crs_epsg_used = models.IntegerField(null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.CASCADE)
    created = models.DateTimeField(
        auto_now_add=True,
        editable=False,
        null=False,
        blank=False)
    status = models.CharField(
        default="initializing",
        max_length=100,
    )
    note = models.CharField(
        blank=True,
        null=True,
        max_length=255,
    )

    def __str__(self):
        return f"{self.document.title} - {self.created}"

    def run(self):

        tkm = TKeywordManager()
        tkm.set_status(self.document, "georeferencing")
        self.update_status("initializing georeferencer")
        try:
            g = Georeferencer(
                transformation=self.transformation_used,
                epsg_code=self.crs_epsg_used,
            )
            g.load_gcps_from_geojson(self.gcps_used)
        except Exception as e:
            self.update_status("failed")
            self.note = f"{e.message}"
            self.save()
            # revert to previous tkeyword status
            tkm.set_status(self.document, "prepared")
            return None
        self.update_status("georeferencing")
        try:
            out_path = g.make_tif(self.document.doc_file.path)
        except Exception as e:
            self.update_status("failed")
            self.note = f"{e.message}"
            self.save()
            # revert to previous tkeyword status
            tkm.set_status(self.document, "prepared")
            return None

        # self.transformation_used = g.transformation["id"]
        self.update_status("creating layer")

        ## need to remove commas from the titles, otherwise the layer will not
        ## be valid in the catalog list when trying to add it to a Map. the 
        ## message in the catalog will read "Missing OGC reference metadata".
        title = self.document.title.replace(",", " -")

        ## first look to see if there is a layer alreaded linked to this document.
        ## this would indicate that it has already been georeferenced, and in this
        ## case the existing layer should be overwritten.
        existing_layer = None
        try:
            link = GeoreferencedDocumentLink.objects.get(document=self.document)
            existing_layer = Layer.objects.get(pk=link.object_id)
        except (GeoreferencedDocumentLink.DoesNotExist, Layer.DoesNotExist):
            pass

        ## create the layer, passing in the existing_layer if present
        layer = file_upload(
            out_path,
            layer=existing_layer,
            overwrite=True,
            title=title,
            user=self.user,
        )

        ## if there was no existing layer, create a new link between the
        ## document and the new layer
        if existing_layer is None:
            ct = ContentType.objects.get(app_label="layers", model="layer")
            GeoreferencedDocumentLink.objects.create(
                document=self.document,
                content_type=ct,
                object_id=layer.pk,
            )

            # set attributes in the layer straight from the document
            for keyword in self.document.keywords.all():
                layer.keywords.add(keyword)
            for region in self.document.regions.all():
                layer.regions.add(region)
            Layer.objects.filter(pk=layer.pk).update(
                date=self.document.date,
                abstract=self.document.abstract,
                category=self.document.category,
                license=self.document.license,
                restriction_code_type=self.document.restriction_code_type,
                attribution=self.document.attribution,
            )

        ## if there was an existing layer that's been overwritten, regenerate thumb.
        else:
            self.update_status("regenerating thumbnail")
            thumb = create_thumbnail(layer, overwrite=True)
            Layer.objects.filter(pk=layer.pk).update(thumbnail_url=thumb)

        self.layer = layer
        self.update_status("saving control points")

        # save the successful gcps to the canonical GCPGroup for the document
        GCPGroup().save_from_geojson(
            self.gcps_used, 
            self.document, 
            self.transformation_used
        )

        tkm.set_status(self.document, "georeferenced")
        tkm.set_status(layer, "georeferenced")

        self.update_status("completed")
        self.save()

        return layer

    def update_status(self, status):
        self.status = status
        self.save(update_fields=['status'])

    def serialize(self):
        return {
            "user": {
                "name": self.user.username,
                "profile": full_reverse("profile_detail", args=(self.user.username, )),
            },
            "date": (self.created.month, self.created.day, self.created.year),
            "date_str": self.created.strftime("%Y-%m-%d"),
            "datetime": self.created.strftime("%Y-%m-%d - %H:%M"),
            "gcps_geojson": self.gcps_used,
            "gcps_ct": len(self.gcps_used["features"]),
            "transformation": self.transformation_used,
            "epsg": self.crs_epsg_used,
            "status": self.status,
        }


class GCP(models.Model):

    class Meta:
        verbose_name = "GCP"
        verbose_name_plural = "GCPs"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pixel_x = models.IntegerField(null=True, blank=True)
    pixel_y = models.IntegerField(null=True, blank=True)
    geom = models.PointField(null=True, blank=True, srid=4326)
    note = models.CharField(null=True, blank=True, max_length=255)
    gcp_group = models.ForeignKey(
        "GCPGroup",
        on_delete=models.CASCADE)

    created = models.DateTimeField(
        auto_now_add=True,
        editable=False,
        null=False,
        blank=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        related_name='created_by',
        on_delete=models.CASCADE)
    last_modified = models.DateTimeField(
        auto_now=True,
        editable=False,
        null=False,
        blank=False)
    last_modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        related_name='modified_by',
        on_delete=models.CASCADE)


class GCPGroup(models.Model):

    TRANSFORMATION_CHOICES = (
        ("tps", "tps"),
        ("poly1", "poly1"),
        ("poly2", "poly2"),
        ("poly3", "poly3"),
    )

    class Meta:
        verbose_name = "GCP Group"
        verbose_name_plural = "GCP Groups"

    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    crs_epsg = models.IntegerField(null=True, blank=True)
    transformation = models.CharField(
        null=True,
        blank=True,
        choices=TRANSFORMATION_CHOICES,
        max_length=20,
    )

    def __str__(self):
        return self.document.title

    @property
    def gcps(self):
        return GCP.objects.filter(gcp_group=self)

    @property
    def gdal_gcps(self):
        gcp_list = []
        for gcp in self.gcps:
            geom = gcp.geom.clone()
            geom.transform(self.crs_epsg)
            p = gdal.GCP(geom.x, geom.y, 0, gcp.pixel_x, gcp.pixel_y)
            gcp_list.append(p)
        return gcp_list

    @property
    def as_geojson(self):

        geo_json = {
          "type": "FeatureCollection",
          "features": []
        }

        for gcp in self.gcps:
            coords = json.loads(gcp.geom.geojson)["coordinates"]
            lat = coords[0]
            lng = coords[1]
            geo_json['features'].append({
                "type": "Feature",
                "properties": {
                  "id": str(gcp.pk),
                  "image": [gcp.pixel_x, gcp.pixel_y],
                  "username": gcp.last_modified_by.username,
                  "note": gcp.note,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [lng, lat]
                }
            })
        return geo_json

    def save_from_geojson(self, geojson, document, transformation=None):
        print("saving gcps")

        group, created = GCPGroup.objects.get_or_create(document=document)

        group.crs_epsg = 3857 # don't see this changing any time soon...
        group.transformation = transformation
        group.save()

        # first remove any existing gcps that have been deleted
        for gcp in group.gcps:
            if str(gcp.id) not in [i['properties'].get('id') for i in geojson['features']]:
                print(f"deleting gcp {gcp.id}")
                gcp.delete()

        for feature in geojson['features']:

            id = feature['properties'].get('id', str(uuid.uuid4()))
            username = feature['properties'].get('username')
            user = get_user_model().objects.get(username=username)
            gcp, created = GCP.objects.get_or_create(
                id = id,
                defaults = {
                    'gcp_group': group,
                    'created_by': user
                })
            print("new gcp created?", created)

            pixel_x = feature['properties']['image'][0]
            pixel_y = feature['properties']['image'][1]
            new_pixel = (pixel_x, pixel_y)
            old_pixel = (gcp.pixel_x, gcp.pixel_y)
            lng = feature['geometry']['coordinates'][0]
            lat = feature['geometry']['coordinates'][1]

            new_geom = Point(lat, lng, srid=4326)

            # only update the point if one of its coordinate pairs have changed,
            # this also triggered when new GCPs have None for pixels and geom.
            if new_pixel != old_pixel or not new_geom.equals(gcp.geom):
                gcp.pixel_x = new_pixel[0]
                gcp.pixel_y = new_pixel[1]
                gcp.geom = new_geom
                gcp.last_modified_by = user
                gcp.save()
                print("coordinates saved/updated")
            else:
                print("gcp coordinates unchanged, no save made")

        return group

    def save_from_annotation(self, annotation, document):

        m = "georeference-ground-control-points"
        georef_annos = [i for i in annotation['items'] if i['motivation'] == m]
        anno = georef_annos[0]

        self.save_from_geojson(anno['body'], document, "poly1")


class LayerMask(models.Model):

    layer = models.ForeignKey(Layer, on_delete=models.CASCADE)
    polygon = models.PolygonField(srid=3857)

    def as_sld(self, indent=False):

        sld = f'''<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
 xsi:schemaLocation="http://www.opengis.net/sld StyledLayerDescriptor.xsd"
 xmlns="http://www.opengis.net/sld"
 xmlns:ogc="http://www.opengis.net/ogc"
 xmlns:xlink="http://www.w3.org/1999/xlink"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<NamedLayer>
 <Name>{self.layer.workspace}:{self.layer.name}</Name>
 <UserStyle IsDefault="true">
  <FeatureTypeStyle>
   <Transformation>
    <ogc:Function name="gs:CropCoverage">
     <ogc:Function name="parameter">
      <ogc:Literal>coverage</ogc:Literal>
     </ogc:Function>
     <ogc:Function name="parameter">
      <ogc:Literal>cropShape</ogc:Literal>
      <ogc:Literal>{self.polygon.wkt}</ogc:Literal>
     </ogc:Function>
    </ogc:Function>
   </Transformation>
   <Rule>
    <RasterSymbolizer>
      <Opacity>1</Opacity>
    </RasterSymbolizer>
   </Rule>
  </FeatureTypeStyle>
 </UserStyle>
</NamedLayer>
</StyledLayerDescriptor>'''

        if indent is False:
            sld = " ".join([i.strip() for i in sld.splitlines()])
            sld = sld.replace("> <","><")

        return sld

    def apply_mask(self):

        cat = get_gs_catalog()

        gs_full_style = cat.get_style(self.layer.name, workspace="geonode")
        trim_style_name = f"{self.layer.name}_trim"

        # create (overwrite if existing) trim style in GeoServer using mask sld
        gs_trim_style = cat.create_style(
            trim_style_name,
            self.as_sld(),
            overwrite=True,
            workspace="geonode",
        )

        # get the GeoServer layer for this GeoNode layer
        gs_layer = cat.get_layer(self.layer.name)

        # add the full and trim styles to the GeoServer alternate style list
        gs_alt_styles = gs_layer._get_alternate_styles()
        gs_alt_styles += [gs_full_style, gs_trim_style]
        gs_layer._set_alternate_styles(gs_alt_styles)

        # set the trim style as the default in GeoServer
        gs_layer._set_default_style(gs_trim_style)

        # save these changes to the GeoServer layer
        cat.save(gs_layer)

        # create/update the GeoNode Style object for the trim style
        trim_style_gn = save_style(gs_trim_style, self.layer)

        # add new trim style to GeoNode list styles, set as default, save
        self.layer.styles.add(trim_style_gn)
        self.layer.default_style = trim_style_gn
        self.layer.save()

        # update thumbnail with new trim style
        thumb = create_thumbnail(self.layer, overwrite=True)
        self.layer.thumbnail_url = thumb
        self.layer.save()

class MaskSession(models.Model):

    class Meta:
        verbose_name = "Mask Session"
        verbose_name_plural = "Mask Sessions"

    layer = models.ForeignKey(Layer, on_delete=models.CASCADE)
    polygon = models.PolygonField(null=True, blank=True, srid=3857)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.CASCADE)
    created = models.DateTimeField(
        auto_now_add=True,
        editable=False,
        null=False,
        blank=False)
    note = models.CharField(
        blank=True,
        null=True,
        max_length=255,
    )

    def run(self):

        ## first get the related Document so the statuses can be managed
        ct = ContentType.objects.get(app_label="layers", model="layer")
        document = GeoreferencedDocumentLink.objects.get(
            content_type=ct,
            object_id=self.layer.pk,
        ).document

        tkm = TKeywordManager()
        tkm.set_status(self.layer, "trimming")
        tkm.set_status(document, "trimming")

        # create/update a LayerMask for this layer and apply it as style
        if self.polygon is not None:

            try:
                mask = LayerMask.objects.get(layer=self.layer)
                mask.polygon = self.polygon
                mask.save()
            except LayerMask.DoesNotExist:
                mask = LayerMask.objects.create(
                    layer=self.layer,
                    polygon=self.polygon,
                )
            mask.apply_mask()

            tkm.set_status(self.layer, "trimmed")
            tkm.set_status(document, "trimmed")

        # if there is no polygon, then clean up old mask styles and reset the
        # default style to original (if needed)
        else:

            # delete the LayerMask object
            LayerMask.objects.filter(layer=self.layer).delete()

            # delete the existing trim style in Geoserver if necessary
            cat = get_gs_catalog()
            trim_style_name = f"{self.layer.name}_trim"
            gs_trim_style = cat.get_style(trim_style_name, workspace="geonode")
            if gs_trim_style is not None:
                cat.delete(gs_trim_style, recurse=True)

            # delete the existing trimmed style in GeoNode
            Style.objects.filter(name=trim_style_name).delete()

            # set the full style back to the default in GeoNode
            gn_full_style = Style.objects.get(name=self.layer.name)
            self.layer.default_style = gn_full_style
            self.layer.save()

            tkm.set_status(self.layer, "georeferenced")
            tkm.set_status(document, "georeferenced")

    def serialize(self):
        vertex_ct = 0
        if self.polygon is not None:
            vertex_ct = len(self.polygon.coords[0]) - 1
        return {
            "user": {
                "name": self.user.username,
                "profile": full_reverse("profile_detail", args=(self.user.username, )),
            },
            "date": (self.created.month, self.created.day, self.created.year),
            "date_str": self.created.strftime("%Y-%m-%d"),
            "datetime": self.created.strftime("%Y-%m-%d - %H:%M"),
            "vertex_ct": vertex_ct,
        }
