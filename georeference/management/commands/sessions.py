from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from georeference.models.sessions import (
    delete_expired_sessions,
    SessionBase,
    PrepSession,
    GeorefSession,
    TrimSession,
)
from georeference.utils import TKeywordManager
from georeference.splitter import Splitter

class Command(BaseCommand):
    help = 'Command line access point for the internal georeferencing utilities.'
    def add_arguments(self, parser):
        parser.add_argument(
            "operation",
            choices=[
                "legacy-migration",
                "run",
                "undo",
                "redo",
                "list",
                "delete-expired",
            ],
            help="specify the operation to carry out",
        )
        parser.add_argument(
            "--type",
            choices=[
                "preparation",
                "georeference",
                "trim",
                "all",
            ],
            help="type of session to manage",
        )
        parser.add_argument(
            "--clean",
            action="store_true",
            help="remove all instances of new sessions before migrating legacy ones",
        )
        parser.add_argument(
            "--pk",
            help="primary key for existing session to manage",
        )
        parser.add_argument(
            "--docid",
            help="document id used to find sessions during list operation",
        )

    def _model_from_type(self, session_type):
        if session_type == "p":
            return PrepSession
        elif session_type == "g":
            return GeorefSession
        elif session_type == "t":
            return TrimSession

    def handle(self, *args, **options):

        operation = options['operation']
        if operation in ['run', 'undo', 'redo']:

            bs = SessionBase.objects.get(pk=options['pk'])
            model = self._model_from_type(bs.type)
            session = model.objects.get(pk=options['pk'])

            if operation == "run":
                session.run()
            elif operation == "redo":
                if bs.type == "p":
                    session.undo(keep_session=True)
                    session.run()
                else:
                    # this is the same as run for georeference sessions
                    # because all previous outputs are reliably overwritten
                    session.run()
            elif operation == "undo":
                session.undo()


        elif operation == "list":

            if options["type"]:
                model = self._model_from_type(options['type'])
                for s in model.objects.filter(document_id=options['docid']):
                    print(s)
            else:
                for ps in PrepSession.objects.filter(document_id=options['docid']):
                    print(ps)
                for gs in GeorefSession.objects.filter(document_id=options['docid']):
                    print(gs)
                for ts in TrimSession.objects.filter(document_id=options['docid']):
                    print(ts)


        elif operation == 'delete-expired':

            delete_expired_sessions()

        elif operation == "legacy-migration":

            self.migrate_legacy_sessions(options['type'], options['clean'])


    def migrate_legacy_sessions(self, type="", clean=False):
        tkm = TKeywordManager()
        try:
            from georeference.models.sessions import (
                SplitEvaluation,
                GeoreferenceSession,
                MaskSession,
            )
        except ImportError:
            exit()
        if type in ["preparation", "all"]:
            if clean is True:
                PrepSession.objects.all().delete()
            for se in SplitEvaluation.objects.all():
                with transaction.atomic():
                    try:
                        ps = PrepSession.objects.create(
                            document=se.document,
                            user=se.user,
                            date_created=se.created,
                            date_run=se.created,
                        )
                        ps.data["split_needed"] = se.split_needed

                        if se.cutlines is None or len(se.cutlines) == 0:
                            ps.data["cutlines"] = []
                            ps.data["divisions"] = []
                        else:
                            ps.data["cutlines"] = se.cutlines
                            s = Splitter(image_file=ps.document.doc_file.path)
                            ps.data['divisions'] = s.generate_divisions(se.cutlines)

                        if tkm.get_status(ps.document) == "splitting":
                            ps.stage = "input"
                            ps.status = "getting user input"
                        else:
                            ps.stage = "finished"
                            ps.status = "success"
                        ps.save()
                    except Exception as e:
                        print(f"error migrating: SplitEvaluation {se.pk}")
                        raise e
        if type in ["georeference", "all"]:
            if clean is True:
                GeoreferenceSession.objects.all().delete()
            for grs in GeoreferenceSession.objects.all():
                with transaction.atomic():
                    try:
                        gs = GeorefSession.objects.create(
                            document=grs.document,
                            layer=grs.layer,
                            user=grs.user,
                            date_created=grs.created,
                            date_run=grs.created,
                        )
                        gs.data["gcps"] = grs.gcps_used
                        gs.data["epsg"] = grs.crs_epsg_used
                        gs.data["transformation"] = grs.transformation_used
                        gs.stage = "finished"
                        gs.status = "success"
                        gs.save()
                    except Exception as e:
                        print(f"error migrating: GeoreferenceSession {grs.pk}")
                        raise e
        if type in ["trim", "all"]:
            if clean is True:
                TrimSession.objects.all().delete()
            for ms in MaskSession.objects.all():
                with transaction.atomic():
                    try:
                        poly = ms.polygon
                        ## this is a session where the mask was deleted. Don't migrate
                        ## this session.
                        if poly is None:
                            print(f"skipping empty session: MaskSession {ms.pk}")
                            continue
                        ts = TrimSession.objects.create(
                            layer=ms.layer,
                            user=ms.user,
                            date_created=ms.created,
                            date_run=ms.created,
                        )
                        ts.data["mask_ewkt"] = ms.polygon.ewkt
                        ts.stage = "finished"
                        ts.status = "success"
                        ts.save()
                    except Exception as e:
                        print(f"error migrating: MaskSession {ms.pk}")
                        raise e
