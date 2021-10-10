import os
import uuid
import json
from osgeo import gdal, osr

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.gis.gdal import SpatialReference, CoordTransform
from django.contrib.gis.geos import Point
from django.contrib.gis.db import models
from django.contrib.postgres.fields import JSONField
from django.core.files import File
from django.utils.translation import ugettext_lazy as _

from geonode.base.models import ThesaurusKeyword
from geonode.documents.models import Document, DocumentResourceLink
from geonode.layers.models import Layer
from geonode.layers.utils import file_upload
from geonode.thumbs.thumbnails import create_thumbnail

from .georeferencer import Georeferencer
from .splitter import Splitter
from .utils import TK

tk = TK()

class SplitDocumentLink(DocumentResourceLink):
    """
    Inherits from the DocumentResourceLink in GeoNode. This allows
    new instances of this model to be used by GeoNode in a default
    manner, while this app can use them in its own way.
    """

    class Meta:
        verbose_name = "Split Document Link"
        verbose_name_plural = "Split Document Links"

    def __str__(self):
        child = Document.objects.get(pk=self.object_id)
        return f"{self.document.__str__()} --> {child.__str__()}"

class Segmentation(models.Model):
    """
    Stores the current segmentation pattern for a given document. These
    properties are generated by the Splitter operations, and then saved
    here for later use in a SplitSession.
    """

    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    no_split_needed = models.BooleanField(default=None, null=True, blank=True)
    segments = JSONField(default=None, null=True, blank=True)
    cutlines = JSONField(default=None, null=True, blank=True)

    def save_from_cutlines(self, cutlines, document):
        """
        This is the preferred method for creating an instance of this model if the document
        needs to be split in the future.
        """

        s = Splitter(image_file=document.doc_file.path)
        segments = s.generate_divisions(cutlines)

        segmentation, created = Segmentation.objects.get_or_create(document=document)
        segmentation.cutlines = cutlines
        segmentation.segments = segments
        segmentation.no_split_needed = False
        segmentation.save()

        return segmentation
    
    def save_without_split(self, document):
        """
        This is the preferred method for creating an instance of this model if the document
        does not need to be split.
        """

        segmentation, created = Segmentation.objects.get_or_create(document=document)
        segmentation.no_split_needed = True
        segmentation.save()

class SplitSession(models.Model):

    class Meta:
        verbose_name = "Split Session"
        verbose_name_plural = "Split Sessions"

    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    no_split_needed = models.BooleanField(default=None, null=True, blank=True)
    segments_used = JSONField(default=None, null=True, blank=True)
    cutlines_used = JSONField(default=None, null=True, blank=True)
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

    def __str__(self):
        return f"{self.document.__str__()} - {self.created_by} - {self.created}"

    def run(self):
        """
        Runs the document split process based on prestored segmentation info
        that has been generated for this document. New Documents are made for
        each child image, SplitDocumentLinks are created to link this parent
        Document with its children. The parent document is also marked as
        metadata_only so that it no longer shows up in the search page lists.
        """

        self.document.tkeywords.remove(tk.unprepared)
        self.document.tkeywords.add(tk.processing)

        segmentation = Segmentation.objects.get(document=self.document)

        if segmentation.no_split_needed is True:
            self.document.tkeywords.remove(tk.unprepared)
            self.document.tkeywords.add(tk.prepared)
            self.no_split_needed = True
            return

        self.segments_used = segmentation.segments
        self.cutlines_used = segmentation.cutlines
        self.no_split_needed = False
        self.save()

        s = Splitter(
            image_file=self.document.doc_file.path,
            divisions=segmentation.segments,
        )
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

            ## this works well and is how the split off segments should be attached
            ## to their parent docs, BUT it is one way. DocumentResourceLink.document
            ## will show the relationship in its interface, but 
            ## DocumentResourceLink.object_id will not.
            ct = ContentType.objects.get(app_label="documents", model="document")
            SplitDocumentLink.objects.create(
                document=self.document,
                content_type=ct,
                object_id=new_doc.pk,
            )

            new_doc.tkeywords.add(tk.prepared)
        
        if len(new_images) > 1:
            self.document.metadata_only = True
            self.document.save()
        self.document.tkeywords.remove(tk.processing)

class GeoreferenceSession(models.Model):

    class Meta:
        verbose_name = "Georeference Session"
        verbose_name_plural = "Georeference Sessions"

    STATUS_CHOICES = (
        ("unstarted", "unstarted"),
        ("failed", "failed"),
        ("georeferencing", "georeferencing"),
        ("layercreation", "layercreation"),
        ("success", "success"),
    )

    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    layer = models.ForeignKey(Layer, null=True, blank=True, on_delete=models.CASCADE)
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
        default="unstarted",
        choices=STATUS_CHOICES,
        max_length=20,
    )
    note = models.CharField(
        blank=True,
        null=True,
        max_length=255,
    )

    def __str__(self):
        return f"{self.document.title} - {self.created}"

    def run(self):

        gcp_group = GCPGroup.objects.get(document=self.document)

        self.gcps_used = gcp_group.as_geojson
        self.crs_epsg_used = gcp_group.crs_epsg
        self.status = "georeferencing"
        self.save()

        try:
            g = Georeferencer(
                gdal_gcps=gcp_group.gdal_gcps,
                transformation=gcp_group.transformation,
                epsg_code=gcp_group.crs_epsg
            )
        except Exception as e:
            self.status = "failed"
            self.message = f"error initializing Georeferencer: {e.message}"
            self.save()
            return None

        out_path = g.georeference(
            self.document.doc_file.path,
            out_format="GTiff",
            addo=True,
        )

        self.transformation_used = g.transformation["id"]
        self.status = "layercreation"
        self.save()

        ## first look to see if there is a layer alreaded linked to this document.
        ## this would indicate that it has already been georeferenced before,
        ## and the existing layer should be overwritten.
        existing_layer = None
        links = DocumentResourceLink.objects.filter(document=self.document)
        for link in links:
            try:
                obj = link.content_type.get_object_for_this_type(pk=link.object_id)
                if isinstance(obj, Layer):
                    existing_layer = obj
            except Layer.DoesNotExist:
                pass

        ## need to remove commas from the titles, otherwise the layer will not
        ## be valid in the catalog list when trying to add it to a Map. the 
        ## message in the catalog will read "Missing OGC reference metadata".
        title = self.document.title.replace(",", " -")

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
            DocumentResourceLink.objects.create(
                document=self.document,
                content_type=ct,
                object_id=layer.pk,
            )

            # set attributes in the layer straight from the document
            layer.date = self.document.date
            layer.abstract = self.document.abstract
            layer.category = self.document.category
            for keyword in self.document.keywords.all():
                layer.keywords.add(keyword)
            for region in self.document.regions.all():
                layer.regions.add(region)
            layer.restriction_code_type = self.document.restriction_code_type
            layer.attribution = self.document.attribution
            layer.license = self.document.license

        ## if there was an existing layer that's been overwritten, regenerate thumb.
        else:
            thumb = create_thumbnail(layer, overwrite=True)
            layer.thumbnail_url = thumb

        layer.save()
        self.layer = layer
        self.status = "success"
        self.save()

        return layer


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
    def as_annotation(self):

        ## this template acquisition should be refactored...
        anno_template = os.path.join(os.path.dirname(__file__), "annotation-template-georeference.json")
        with open(anno_template, "r") as o:
            anno = json.loads(o.read())

        ## WARNING: the order of the coordinates in the geometry below
        ## may need to be switched. see as_geojson() for example.
        for gcp in self.gcps:
            gcp_feat = {
                "type": "Feature",
                "properties": {
                  "id": str(gcp.pk),
                  "pixel": [gcp.pixel_x, gcp.pixel_y]
                },
                "geometry": json.loads(gcp.geom.geojson)
              }
            anno['items'][0]['body']['features'].append(gcp_feat)

        return anno

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
