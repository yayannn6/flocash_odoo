from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

class FlocashCallback(http.Controller):

    @http.route(['/flocash/callback'], type='http', auth='public', csrf=False, methods=['POST'])
    def flocash_callback(self, **post):
        """ Callback dari Flocash setelah pembayaran """
        try:
            raw_data = request.httprequest.data.decode("utf-8") if request.httprequest.data else ""
            data = {}

            # 1. Jika POST form
            if post:
                data = post
            # 2. Jika raw x-www-form-urlencoded
            elif raw_data and "=" in raw_data:
                from urllib.parse import parse_qs
                parsed = parse_qs(raw_data)
                data = {k: v[0] for k, v in parsed.items()}
            # 3. Jika JSON
            elif raw_data:
                try:
                    data = json.loads(raw_data)
                except Exception:
                    data = {}

            _logger.info("Flocash callback received: %s", data)

            order_id = data.get("orderId")
            trace_number = data.get("traceNumber")
            amount = float(data.get("amount", 0.0))

            if not order_id or not trace_number:
                return request.make_json_response({"status": "error", "message": "Invalid data"}, status=400)

            # Cari invoice berdasarkan orderId (payment_reference)
            invoice = request.env['account.move'].sudo().search([('payment_reference', '=', order_id)], limit=1)
            if not invoice:
                return request.make_json_response({"status": "error", "message": "Invoice not found"}, status=404)

            # Cek apakah payment sudah ada
            existing_payment = request.env['account.payment'].sudo().search([('trace_number', '=', trace_number)], limit=1)
            if existing_payment:
                return request.make_json_response({"status": "ok", "message": "Payment already processed"})

            # Buat payment
            journal = request.env['account.journal'].sudo().search([('type', '=', 'bank')], limit=1)
            payment_vals = {
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'partner_id': invoice.partner_id.id,
                'amount': amount,
                'currency_id': invoice.currency_id.id,
                'journal_id': journal.id,
                'payment_method_id': request.env.ref('account.account_payment_method_manual_in').id,
                'ref': f"Flocash {trace_number}",
                'trace_number': trace_number,
            }
            payment = request.env['account.payment'].sudo().create(payment_vals)
            payment.action_post()

            # Rekonsiliasi
            (payment.line_ids + invoice.line_ids).reconcile()

            # Kirim email notifikasi
            template = request.env.ref("yayan_flocash.email_template_payment_done", raise_if_not_found=False)
            if template:
                template.sudo().send_mail(invoice.id, force_send=True)

            return request.make_json_response({
                "status": "ok",
                "message": "Payment processed",
                "invoice": invoice.name,
                "amount": amount,
                "trace_number": trace_number,
            })

        except Exception as e:
            _logger.exception("Error in Flocash callback")
            return request.make_json_response({"status": "error", "message": str(e)}, status=500)
