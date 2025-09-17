import base64
import requests
from odoo import models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = "account.move"

    flocash_link = fields.Char("Flocash Payment Link", copy=False)
    flocash_payment_option = fields.Selection(
        selection=[
            ("140", "Ecobank Branch Payment"),
            ("145", "Debit / Credit Cards"),
            ("127", "Migs - UBA"),
            ("105", "M-Pesa"),
        ],
        string="Flocash Payment Option",
        default="145",
        help="Choose payment option for Flocash",
    )
    trace_number = fields.Char("Trace Number", copy=False)

    def _cron_check_flocash_payment(self):
        """Scheduled Action: Check unpaid invoices with Flocash trace_number"""
        invoices = self.env["account.move"].search([
            ("move_type", "=", "out_invoice"),   # customer invoice
            ("payment_state", "!=", "paid"),     # not yet paid
            ("trace_number", "!=", False),       # has trace number
        ])

        _logger.info("Flocash Cron found %s invoices to check", len(invoices))

        for inv in invoices:
            try:
                inv.action_check_flocash_payment()
            except Exception as e:
                _logger.exception("Error checking Flocash payment for invoice %s", inv.name)

    def action_invoice_sent(self):
        for inv in self:
            if inv.move_type == "out_invoice" and not inv.flocash_link:
                inv.action_create_flocash_link()
        return super().action_invoice_sent()

    def action_create_flocash_link(self):
        for inv in self:
            if inv.move_type != "out_invoice":
                continue

            provider = self.env["payment.provider"].search([("code", "=", "flocash")], limit=1)
            if not provider:
                raise UserError("Flocash provider is not configured")

            auth_str = f"{provider.flocash_api_username}:{provider.flocash_api_password}"
            auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

            base_url = (
                "https://sandbox.flocash.com/rest/v2"
                if provider.flocash_environment == "sandbox"
                else "https://pay.flocash.com/rest/v2"
            )

            url = f"{base_url}/paylinks"

            payload = {
                "order": {
                    "custom": str(inv.name),
                    "amount": str(inv.amount_total),
                    "orderId": str(inv.id),
                    "currency": inv.currency_id.name,
                    "item_name": f"Invoice {inv.name}",
                    "item_price": str(inv.amount_total),
                    "quantity": "1",
                },
                "merchant": {
                    "merchantAccount": provider.flocash_merchant_account
                },
                "payOption": {"id": inv.flocash_payment_option},  
                "payer": {
                    "country": inv.partner_id.country_id.code or "US",
                    "firstName": (inv.partner_id.name).split(" ")[0],
                    "lastName": (inv.partner_id.name or "X").split(" ")[-1],
                    "mobile": inv.partner_id.phone or "",
                    "email": inv.partner_id.email or "",
                },
            }

            headers = {
                "api-version": "1.5",
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth}",
            }

            response = requests.post(url, headers=headers, json=payload, timeout=30)

            if response.status_code in (200, 201):
                data = response.json()
                invoice_link = data.get("order", {}).get("invoiceLink")
                trace_number = data.get("order", {}).get("traceNumber", "")
                if invoice_link:
                    inv.flocash_link = invoice_link
                    inv.trace_number = trace_number
                    # _logger.info("Flocash link generated: %s", invoice_link)
                else:
                    raise ValueError(f"Flocash response missing invoiceLink: {data}")
            else:
                raise ValueError(f"Flocash error {response.status_code}: {response.text}")

    def action_check_flocash_payment(self):
        """Cek pembayaran Flocash dan buat pembayaran jika captureAmount > 0"""
        for inv in self:
            if not inv.trace_number:
                continue  # Skip jika tidak ada trace_number

            provider = self.env["payment.provider"].search([("code", "=", "flocash")], limit=1)
            if not provider:
                raise UserError("Flocash provider is not configured")

            # Auth
            auth_str = f"{provider.flocash_api_username}:{provider.flocash_api_password}"
            auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

            # URL
            base_url = (
                "https://sandbox.flocash.com/rest/v2"
                if provider.flocash_environment == "sandbox"
                else "https://pay.flocash.com/rest/v2"
            )
            url = f"{base_url}/orders/{inv.trace_number}"
            headers = {
                "api-version": "1.5",
                "Authorization": f"Basic {auth}",
            }

            # Request
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code not in (200, 201):
                raise UserError(f"Failed to fetch Flocash order: {response.status_code} - {response.text}")

            data = response.json()
            order_data = data.get("order", {}) if isinstance(data, dict) else {}

            # Ambil captureAmount
            capture_amount = float(order_data.get("capturedAmount") or 0.0)

            if capture_amount <= 0:
                raise UserError("Belum ada pembayaran yang dicapture di Flocash.")

            # Cegah pembayaran dobel
            if inv.payment_state == "paid":
                raise UserError(f"Invoice {inv.name} sudah lunas, tidak bisa buat payment baru.")

            # Cari journal bank
            journal = self.env["account.journal"].search(
                [("type", "=", "bank"), ("company_id", "=", inv.company_id.id)],
                limit=1
            )
            if not journal:
                raise UserError("Tidak ada Bank Journal untuk perusahaan ini.")

            # Buat & langsung post payment
            payment_vals = {
                "date": fields.Date.context_today(self),
                "amount": capture_amount,
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": inv.partner_id.id,
                "currency_id": inv.currency_id.id,
                "journal_id": journal.id,
                "payment_method_id": self.env.ref("account.account_payment_method_manual_in").id,
            }
            payment = self.env["account.payment"].create(payment_vals)
            inv.matched_payment_ids = [(4, payment.id)]
            payment.action_post()
            payment.action_validate()
            # Rekonsiliasi otomatis
            payment_lines = payment.move_id.line_ids.filtered(lambda l: l.account_id.internal_group == "asset_receivable")
            invoice_lines = inv.line_ids.filtered(lambda l: l.account_id.internal_group == "asset_receivable")
            (payment_lines + invoice_lines).reconcile()
            self._send_payment_notifications(capture_amount, payment)


    def _send_payment_notifications(self, capture_amount, payment):
        """Send payment confirmation messages to customer and internal user"""
        for inv in self:
            # === Message to customer ===
            if inv.partner_id.email:
                subject = f"Payment Confirmation for Invoice {inv.name}"
                body = (
                    f"Dear {inv.partner_id.name},<br/><br/>"
                    f"We have received your payment of <b>{capture_amount:.2f} {inv.currency_id.name}</b> "
                    f"for invoice <b>{inv.name}</b>.<br/><br/>"
                    "Thank you for your business.<br/><br/>"
                    "Best regards,<br/>"
                    f"{inv.company_id.name}"
                )
                mail_values = {
                    "subject": subject,
                    "body_html": body,
                    "email_to": inv.partner_id.email,
                    "email_from": inv.company_id.email or self.env.user.email_formatted,
                }
                self.env["mail.mail"].create(mail_values).send()

            # === Message to Odoo internal user ===
            user = inv.invoice_user_id or inv.create_uid
            if user and user.email:
                subject = f"Customer Payment Received for Invoice {inv.name}"
                body = (
                    f"Hello {user.name},<br/><br/>"
                    f"The customer <b>{inv.partner_id.name}</b> has made a payment of "
                    f"<b>{capture_amount:.2f} {inv.currency_id.name}</b> "
                    f"for invoice <b>{inv.name}</b>.<br/><br/>"
                    f"Payment reference: {payment.name}<br/>"
                    f"Trace Number: {inv.trace_number}<br/><br/>"
                    "Regards,<br/>"
                    "Odoo System"
                )
                mail_values = {
                    "subject": subject,
                    "body_html": body,
                    "email_to": user.email,
                    "email_from": inv.company_id.email or self.env.user.email_formatted,
                }
                self.env["mail.mail"].create(mail_values).send()



class PaymentProvider(models.Model):
    _inherit = "payment.provider"

    code = fields.Selection(
        selection_add=[("flocash", "Flocash")],
        ondelete={"flocash": "set default"},
    )

    # Credentials
    flocash_api_username = fields.Char("Flocash API Username")
    flocash_api_password = fields.Char("Flocash API Password")
    flocash_merchant_account = fields.Char("Flocash Merchant Account")

    # Sandbox / Production toggle
    flocash_environment = fields.Selection(
        [("sandbox", "Sandbox"), ("production", "Production")],
        default="sandbox",
        string="Environment"
    )

    def _get_api_base(self):
        if self.flocash_environment == "sandbox":
            return "https://sandbox.flocash.com/rest/v2"
        return "https://pay.flocash.com/rest/v2"


