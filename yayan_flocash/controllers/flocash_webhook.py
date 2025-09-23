from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

class FlocashCallback(http.Controller):

    @http.route(['/flocash/callback'], type='json', auth='public', csrf=False)
    def flocash_callback(self, **kw):
        """ Callback dari Flocash setelah pembayaran """
        try:
            data = request.jsonrequest or kw
            _logger.info("Flocash callback received: %s", data)

            order_id = data.get("orderId")
            trace_number = data.get("traceNumber")
            amount = float(data.get("amount", 0.0))
            currency = data.get("currencyName")

            if not order_id or not trace_number:
                return {"status": "error", "message": "Invalid data"}

            # Cari invoice berdasarkan orderId
            invoice = request.env['account.move'].sudo().search([('payment_reference', '=', order_id)], limit=1)
            if not invoice:
                return {"status": "error", "message": "Invoice not found"}

            # Cek apakah payment sudah ada
            existing_payment = request.env['account.payment'].sudo().search([('trace_number', '=', trace_number)], limit=1)
            if existing_payment:
                return {"status": "ok", "message": "Payment already processed"}

            # Buat payment baru
            payment_vals = {
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'partner_id': invoice.partner_id.id,
                'amount': amount,
                'currency_id': invoice.currency_id.id,
                'journal_id': request.env['account.journal'].sudo().search([('type', '=', 'bank')], limit=1).id,
                'payment_method_id': request.env.ref('account.account_payment_method_manual_in').id,
                'ref': f"Flocash {trace_number}",
                'trace_number': trace_number,
            }
            payment = request.env['account.payment'].sudo().create(payment_vals)
            payment.action_post()

            # Rekonsiliasi payment ke invoice
            (payment.line_ids + invoice.line_ids).reconcile()

            # Kirim pesan ke customer & user (seperti yang sudah kamu buat sebelumnya)
            template = request.env.ref("yayan_flocash.email_template_payment_done")
            if template:
                template.sudo().send_mail(invoice.id, force_send=True)

            # Tampilkan halaman sukses
            return request.render("yayan_flocash.portal_payment_success_page", {
                "invoice": invoice,
                "payment": payment,
                "trace_number": trace_number,
            })

        except Exception as e:
            _logger.exception("Error in Flocash callback")
            return {"status": "error", "message": str(e)}
