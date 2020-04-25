# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import pprint
import requests
import werkzeug

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PayphoneController(http.Controller):
    _notify_url = '/payment/processpayment'
    _return_url = '/payment/processpayment'

    def _payphone_validate_data(self, **post):
        resp = post.get('trade_status')
        if resp:
            if resp in ['TRADE_FINISHED', 'TRADE_SUCCESS']:
                _logger.info('Payphone: validated data')
            elif resp == 'TRADE_CLOSED':
                _logger.warning('Payphone: payment refunded to user and closed the transaction')
            else:
                _logger.warning('Payphone: unrecognized payphone answer, received %s instead of TRADE_FINISHED/TRADE_SUCCESS and TRADE_CLOSED' % (post['trade_status']))
        if post.get('out_trade_no') and post.get('trade_no'):
            post['reference'] = request.env['payment.transaction'].sudo().search([('reference', '=', post['out_trade_no'])]).reference
            return request.env['payment.transaction'].sudo().form_feedback(post, 'payphone')
        return False

    def _payphone_validate_notification(self, **post):
        if post.get('out_trade_no'):
            payphone = request.env['payment.transaction'].sudo().search([('reference', '=', post.get('out_trade_no'))]).acquirer_id
        else:
            payphone = request.env['payment.acquirer'].sudo().search([('provider', '=', 'payphone')])
        val = {
            'service': 'notify_verify',
            'partner': payphone.payphone_merchant_partner_id,
            'notify_id': post['notify_id']
        }
        response = requests.post(payphone._get_form_action_url(), val)
        response.raise_for_status()
        _logger.info('Validate payphone Notification %s' % response.text)
        # After program is executed, the page must print “success” (without quote). If not, Payphone server would keep
        # re-sending notification, until over 24 hour 22 minutes Generally, there are 8 notifications within 25 hours
        # (Frequency: 2m,10m,15m,1h,2h,6h,15h)
        if response.text == 'true':
            self._payphone_validate_data(**post)
            return 'success'
        return ""

    @http.route('/payment/processpayment', type='http', auth="public", methods=['GET', 'POST'])
    def payphone_return(self, **post):
        """ Payphone return """
        _logger.info('Beginning payphone form_feedback with post data %s', pprint.pformat(post))
        self._payphone_validate_data(**post)
        return werkzeug.utils.redirect('payment/processpayment')

    @http.route('/payment/processpayment', type='http', auth='public', methods=['POST'], csrf=False)
    def payphone_notify(self, **post):
        """ Payphone Notify """
        _logger.info('Beginning Payphone notification form_feedback with post data %s', pprint.pformat(post))
        return self._payphone_validate_notification(**post)
