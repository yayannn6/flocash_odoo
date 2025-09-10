import base64
import requests
from odoo import models, fields
from odoo.exceptions import UserError

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
                "payOption": {"id": inv.flocash_payment_option},  # sebaiknya ambil dinamis via /payoptions
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
                if invoice_link:
                    inv.flocash_link = invoice_link
                    # _logger.info("Flocash link generated: %s", invoice_link)
                else:
                    raise ValueError(f"Flocash response missing invoiceLink: {data}")
            else:
                raise ValueError(f"Flocash error {response.status_code}: {response.text}")



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

