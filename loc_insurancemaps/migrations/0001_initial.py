# Generated by Django 3.2.18 on 2023-04-04 19:44

from django.conf import settings
import django.contrib.gis.db.models.fields
from django.db import migrations, models
import django.db.models.deletion
import georeference.storage
import loc_insurancemaps.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('georeference', '0001_initial'),
        ('places', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Volume',
            fields=[
                ('identifier', models.CharField(max_length=100, primary_key=True, serialize=False)),
                ('city', models.CharField(max_length=100)),
                ('county_equivalent', models.CharField(blank=True, max_length=100, null=True)),
                ('state', models.CharField(choices=[('alabama', 'Alabama'), ('alaska', 'Alaska'), ('arizona', 'Arizona'), ('arkansas', 'Arkansas'), ('california', 'California'), ('colorado', 'Colorado'), ('connecticut', 'Connecticut'), ('delaware', 'Delaware'), ('florida', 'Florida'), ('georgia', 'Georgia'), ('hawaii', 'Hawaii'), ('idaho', 'Idaho'), ('illinois', 'Illinois'), ('indiana', 'Indiana'), ('iowa', 'Iowa'), ('kansas', 'Kansas'), ('kentucky', 'Kentucky'), ('louisiana', 'Louisiana'), ('maine', 'Maine'), ('maryland', 'Maryland'), ('massachusetts', 'Massachusetts'), ('michigan', 'Michigan'), ('minnesota', 'Minnesota'), ('mississippi', 'Mississippi'), ('missouri', 'Missouri'), ('montana', 'Montana'), ('nebraska', 'Nebraska'), ('nevada', 'Nevada'), ('new hampshire', 'New Hampshire'), ('new jersey', 'New Jersey'), ('new mexico', 'New Mexico'), ('new york', 'New York'), ('north carolina', 'North Carolina'), ('north dakota', 'North Dakota'), ('ohio', 'Ohio'), ('oklahoma', 'Oklahoma'), ('oregon', 'Oregon'), ('pennsylvania', 'Pennsylvania'), ('rhode island', 'Rhode Island'), ('south carolina', 'South Carolina'), ('south dakota', 'South Dakota'), ('tennessee', 'Tennessee'), ('texas', 'Texas'), ('utah', 'Utah'), ('vermont', 'Vermont'), ('virginia', 'Virginia'), ('washington', 'Washington'), ('west virginia', 'West Virginia'), ('wisconsin', 'Wisconsin'), ('wyoming', 'Wyoming')], max_length=50)),
                ('year', models.IntegerField(choices=[(1867, 1867), (1868, 1868), (1869, 1869), (1870, 1870), (1871, 1871), (1872, 1872), (1873, 1873), (1874, 1874), (1875, 1875), (1876, 1876), (1877, 1877), (1878, 1878), (1879, 1879), (1880, 1880), (1881, 1881), (1882, 1882), (1883, 1883), (1884, 1884), (1885, 1885), (1886, 1886), (1887, 1887), (1888, 1888), (1889, 1889), (1890, 1890), (1891, 1891), (1892, 1892), (1893, 1893), (1894, 1894), (1895, 1895), (1896, 1896), (1897, 1897), (1898, 1898), (1899, 1899), (1900, 1900), (1901, 1901), (1902, 1902), (1903, 1903), (1904, 1904), (1905, 1905), (1906, 1906), (1907, 1907), (1908, 1908), (1909, 1909), (1910, 1910), (1911, 1911), (1912, 1912), (1913, 1913), (1914, 1914), (1915, 1915), (1916, 1916), (1917, 1917), (1918, 1918), (1919, 1919), (1920, 1920), (1921, 1921), (1922, 1922), (1923, 1923), (1924, 1924), (1925, 1925), (1926, 1926), (1927, 1927), (1928, 1928), (1929, 1929), (1930, 1930), (1931, 1931), (1932, 1932), (1933, 1933), (1934, 1934), (1935, 1935), (1936, 1936), (1937, 1937), (1938, 1938), (1939, 1939), (1940, 1940), (1941, 1941), (1942, 1942), (1943, 1943), (1944, 1944), (1945, 1945), (1946, 1946), (1947, 1947), (1948, 1948), (1949, 1949), (1950, 1950), (1951, 1951), (1952, 1952), (1953, 1953), (1954, 1954), (1955, 1955), (1956, 1956), (1957, 1957), (1958, 1958), (1959, 1959), (1960, 1960), (1961, 1961), (1962, 1962), (1963, 1963), (1964, 1964), (1965, 1965), (1966, 1966), (1967, 1967), (1968, 1968), (1969, 1969)])),
                ('month', models.IntegerField(blank=True, choices=[(1, 'JAN.'), (2, 'FEB.'), (3, 'MAR.'), (4, 'APR.'), (5, 'MAY.'), (6, 'JUN.'), (7, 'JUL.'), (8, 'AUG.'), (9, 'SEP.'), (10, 'OCT.'), (11, 'NOV.'), (12, 'DEC.')], null=True)),
                ('volume_no', models.CharField(blank=True, max_length=5, null=True)),
                ('lc_item', models.JSONField(blank=True, default=None, null=True)),
                ('lc_resources', models.JSONField(blank=True, default=None, null=True)),
                ('lc_manifest_url', models.CharField(blank=True, max_length=200, null=True, verbose_name='LC Manifest URL')),
                ('extra_location_tags', models.JSONField(blank=True, default=list, null=True)),
                ('sheet_ct', models.IntegerField(blank=True, null=True)),
                ('status', models.CharField(choices=[('not started', 'not started'), ('initializing...', 'initializing...'), ('started', 'started'), ('all georeferenced', 'all georeferenced')], default='not started', max_length=50)),
                ('load_date', models.DateTimeField(blank=True, null=True)),
                ('ordered_layers', models.JSONField(blank=True, default=loc_insurancemaps.models.default_ordered_layers_dict, null=True)),
                ('document_lookup', models.JSONField(blank=True, default=dict, null=True)),
                ('layer_lookup', models.JSONField(blank=True, default=dict, null=True)),
                ('sorted_layers', models.JSONField(default=loc_insurancemaps.models.default_sorted_layers_dict)),
                ('multimask', models.JSONField(blank=True, null=True)),
                ('mosaic_geotiff', models.FileField(blank=True, max_length=255, null=True, storage=georeference.storage.OverwriteStorage(), upload_to='mosaics')),
                ('extent', django.contrib.gis.db.models.fields.PolygonField(blank=True, null=True, srid=4326)),
                ('loaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('locales', models.ManyToManyField(blank=True, to='places.Place')),
            ],
        ),
        migrations.CreateModel(
            name='Sheet',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sheet_no', models.CharField(blank=True, max_length=10, null=True)),
                ('lc_iiif_service', models.CharField(blank=True, max_length=150, null=True)),
                ('jp2_url', models.CharField(blank=True, max_length=150, null=True)),
                ('doc', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='georeference.document')),
                ('volume', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='loc_insurancemaps.volume')),
            ],
        ),
    ]
