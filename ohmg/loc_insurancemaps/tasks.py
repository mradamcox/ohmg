from ohmg.celeryapp import app
from ohmg.content.models import Map
from ohmg.loc_insurancemaps.models import Volume

@app.task
def load_docs_as_task(volume_id):
    volume = Volume.objects.get(pk=volume_id)
    volume.load_sheet_docs()

@app.task
def generate_mosaic_cog_task(volume_id):
    map = Map(volume_id)
    map.generate_mosaic_cog()

@app.task
def generate_mosaic_json_task(volume_id, trim_all=False):
    map = Map(volume_id)
    map.generate_mosaic_json(trim_all=trim_all)
