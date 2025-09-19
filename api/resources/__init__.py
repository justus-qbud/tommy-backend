from flask_restful import Api

from api.resources.Catalog import Catalog, CatalogSearch

api = Api(prefix="/api/v1", catch_all_404s=True)

api.add_resource(Catalog, "/catalog/<uuid:catalog_id>")
api.add_resource(CatalogSearch, "/catalog/<uuid:catalog_id>/search")
