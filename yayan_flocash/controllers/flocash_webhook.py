import logging
from odoo import http

_logger = logging.getLogger(__name__)

class FlocashWebhook(http.Controller):

    @http.route("/flocash/callback", type="json", auth="public", methods=["POST"], csrf=False)
    def flocash_callback(self, **post):
        _logger.info("Flocash callback: %s", post)
        order_id = post.get("orderId")
        status = post.get("status")

        invoice = http.request.env["account.move"].sudo().search([("name", "=", order_id)], limit=1)
        if invoice and status == "SUCCESS":
            invoice.action_post()
            invoice.payment_state = "paid"
        return {"status": "ok"}
