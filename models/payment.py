# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import hashlib

from werkzeug import urls

from odoo import api, fields, models, _
from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.tools.float_utils import float_compare
import requests
import random

import logging

_logger = logging.getLogger(__name__)


class PaymentAcquirerPayphone(models.Model):
    _inherit = 'payment.acquirer'

    provider = fields.Selection(selection_add=[('payphone', 'Payphone')])

    def _get_payphone_urls(self):
        """ payphone URLs"""
        payphone_gateway = self.env['payphone.config'].search([
            ('company_id', '=', self.company_id.id), ])

        if not payphone_gateway.id:
            raise Exception("Must be set the payphone config ")

        seq = int(random.random() * 100000)

        data = {
            "amount": 10,
            "tax": 0,
            "amountWithTax": 0,
            "amountWithoutTax": 10,
            "service": 0,
            "tip": 0,
            "currency": "USD",
            "reference": "string",
            "clientTransactionId": str(seq),
            "storeId": payphone_gateway.id_commerce,
            "additionalData": "string",
            "oneTime": True,
            "expireIn": 10
        }

        headers = {
            'content-type': "application/json",
            'Authorization': "Bearer "+payphone_gateway.token
        }

        url = requests.get(payphone_gateway.url+"api/Links", json=data, headers=headers)

        return {'payphone_form_url': url.json()['url']}

    def payphone_form_generate_values(self, values):
        self.ensure_one()
        base_url = self.get_base_url()

        payphone_gateway = self.env['payphone.config'].search([
            ('company_id', '=', self.company_id.id), ])

        payphone_values = dict(values,
                               key=payphone_gateway.token,
                               txnid=values['reference'],
                               amount=values['amount'],
                               amountWithoutTax=values['amount'],
                               productinfo=values['reference'],
                               firstname=values.get('partner_name'),
                               email=values.get('partner_email'),
                               phone=values.get('partner_phone'),
                               countryCode=payphone_gateway.region,
                               service_provider='payphone',
                               currency='USD',
                               surl=urls.url_join(base_url, '/payment/processpayment/'),
                               furl=urls.url_join(base_url, '/payment/processpayment/'),
                               curl=urls.url_join(base_url, '/payment/processpayment/')
                               )

        payphone_values['udf1'] = payphone_values.pop('return_url', '/')
        return payphone_values

    def payphone_get_form_action_url(self):
        self.ensure_one()
        return self._get_payphone_urls()['payphone_form_url']


class PaymentTransactionPayphone(models.Model):
    _inherit = 'payment.transaction'

    @api.model
    def _payphone_form_get_tx_from_data(self, data):
        """ Given a data dict coming from payumoney, verify it and find the related
        transaction record. """
        reference = data.get('txnid')
        pay_id = data.get('mihpayid')
        shasign = data.get('hash')
        if not reference or not pay_id or not shasign:
            raise ValidationError(
                _('Payphone: received data with missing reference (%s) or pay_id (%s) or shashign (%s)') % (
                    reference, pay_id, shasign))

        transaction = self.search([('reference', '=', reference)])

        if not transaction:
            error_msg = (_('Payphone: received data for reference %s; no order found') % (reference))
            raise ValidationError(error_msg)
        elif len(transaction) > 1:
            error_msg = (_('Payphone: received data for reference %s; multiple orders found') % (reference))
            raise ValidationError(error_msg)

        # verify shasign
        shasign_check = transaction.acquirer_id._payphone_generate_sign('out', data)
        if shasign_check.upper() != shasign.upper():
            raise ValidationError(
                _('Payphone: invalid shasign, received %s, computed %s, for data %s') % (shasign, shasign_check, data))
        return transaction

    def _payphone_form_get_invalid_parameters(self, data):
        invalid_parameters = []

        if self.acquirer_reference and data.get('mihpayid') != self.acquirer_reference:
            invalid_parameters.append(
                ('Transaction Id', data.get('mihpayid'), self.acquirer_reference))
        # check what is buyed
        if float_compare(float(data.get('amount', '0.0')), self.amount, 2) != 0:
            invalid_parameters.append(
                ('Amount', data.get('amount'), '%.2f' % self.amount))

        return invalid_parameters

    def _payphone_form_validate(self, data):
        status = data.get('status')
        result = self.write({
            'acquirer_reference': data.get('payphoneMoneyId'),
            'date': fields.Datetime.now(),
        })
        if status == 'success':
            self._set_transaction_done()
        elif status != 'pending':
            self._set_transaction_cancel()
        else:
            self._set_transaction_pending()
        return result
