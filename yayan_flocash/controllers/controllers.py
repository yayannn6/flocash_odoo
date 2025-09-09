# -*- coding: utf-8 -*-
# from odoo import http


# class YayanFlocash(http.Controller):
#     @http.route('/yayan_flocash/yayan_flocash', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/yayan_flocash/yayan_flocash/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('yayan_flocash.listing', {
#             'root': '/yayan_flocash/yayan_flocash',
#             'objects': http.request.env['yayan_flocash.yayan_flocash'].search([]),
#         })

#     @http.route('/yayan_flocash/yayan_flocash/objects/<model("yayan_flocash.yayan_flocash"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('yayan_flocash.object', {
#             'object': obj
#         })

