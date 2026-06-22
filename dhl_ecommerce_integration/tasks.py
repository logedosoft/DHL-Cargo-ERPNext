# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import time
import frappe
import requests
from urllib.parse import quote
from frappe.utils import add_to_date, now_datetime

from dhl_ecommerce_integration.utils import get_token, _log_api_request

DHL_STATUS_MAP = {
	1: "Pending",
	2: "In Transfer",
	3: "In Transit",
	4: "Out for Delivery",
	5: "Delivered",
	6: "Delivery Failed",
	7: "Returning",
	8: "Support Needed",
}

TERMINAL_STATUSES = ["Delivered", "Delivery Failed", "Returning", "Support Needed", "Not Found"]

MAX_RETRY_ATTEMPTS = 3
BACKOFF_SECONDS = [1, 2, 4]
MAX_TRACKING_BATCH_SIZE = 1000


def dhl_hourly_tracking():
	dctResult = frappe._dict({"op_result": True, "op_message": "", "processed": 0, "failed": 0})

	docSettings = frappe.get_single("DHL Cargo Settings")
	if not docSettings.enabled:
		dctResult.op_message = "DHL Cargo Settings is not enabled"
	elif not docSettings.web_service_url:
		dctResult.op_result = False
		dctResult.op_message = "DHL Cargo Settings web service URL is not configured"
		frappe.log_error("DHL Hourly Tracking", dctResult.op_message)
	else:
		dctTokenResult = get_token()
		if not dctTokenResult.op_result:
			dctResult.op_result = False
			dctResult.op_message = "Failed to obtain DHL token: " + dctTokenResult.op_message
			frappe.log_error("DHL Hourly Tracking", dctResult.op_message)
		else:
			dctHeaders = _build_headers(docSettings, dctTokenResult.token)
			lstDNs = _get_active_delivery_notes()

			for dctDN in lstDNs:
				try:
					_track_single_dn(dctDN, dctHeaders, docSettings)
					dctResult.processed += 1
				except Exception:
					dctResult.failed += 1
					frappe.log_error(
						"DHL Hourly Tracking DN Exception",
						"ReferenceId: {0} | {1}".format(dctDN.get("dhl_reference_id") or "", frappe.get_traceback())
					)

	return dctResult


def _get_active_delivery_notes():
	dtOneHourAgo = add_to_date(now_datetime(), hours=-1)

	lstRows = frappe.get_all(
		"Delivery Note",
		filters=[
			["dhl_reference_id", "is", "set"],
			["dhl_reference_id", "!=", ""],
			["docstatus", "=", 1],
			["is_return", "=", 0],
		],
		or_filters=[
			["dhl_shipment_status", "is", "not set"],
			["dhl_shipment_status", "not in", TERMINAL_STATUSES],
		],
		fields=["name", "dhl_reference_id", "dhl_shipment_status", "dhl_last_tracked"],
		limit_page_length=MAX_TRACKING_BATCH_SIZE
	)

	lstActive = []
	for dctRow in lstRows:
		dtLastTracked = dctRow.get("dhl_last_tracked")
		if dtLastTracked and dtLastTracked >= dtOneHourAgo:
			continue
		lstActive.append(dctRow)

	return lstActive


def _build_headers(docSettings, strToken):
	return {
		"x-ibm-client-id": docSettings.client_id,
		"x-ibm-client-secret": docSettings.get_password("client_secret"),
		"Content-Type": "application/json",
		"Authorization": "Bearer " + strToken
	}


def _track_single_dn(dctDN, dctHeaders, docSettings):
	strReferenceId = dctDN.get("dhl_reference_id") or ""
	strOldStatus = dctDN.get("dhl_shipment_status") or ""
	strNewStatus = ""
	strErrorMessage = ""

	if not _is_valid_reference_id(strReferenceId):
		strErrorMessage = "Invalid referenceId format"
	else:
		strBaseURL = docSettings.web_service_url
		dctStatusResult = _fetch_shipment_status(strReferenceId, strBaseURL, dctHeaders, docSettings)

		if dctStatusResult.op_result:
			strNewStatus = dctStatusResult.status
		elif dctStatusResult.status_code == 401:
			dctTokenResult = get_token(blnForce=True)
			if dctTokenResult.op_result:
				dctHeaders = _build_headers(docSettings, dctTokenResult.token)
				dctStatusResult = _fetch_shipment_status(strReferenceId, strBaseURL, dctHeaders, docSettings)
				if dctStatusResult.op_result:
					strNewStatus = dctStatusResult.status
				elif dctStatusResult.status_code == 404:
					strNewStatus = _resolve_order_status(strReferenceId, strBaseURL, dctHeaders, docSettings)
				else:
					strErrorMessage = dctStatusResult.op_message
			else:
				strErrorMessage = "Token refresh failed: " + dctTokenResult.op_message
		elif dctStatusResult.status_code == 404:
			strNewStatus = _resolve_order_status(strReferenceId, strBaseURL, dctHeaders, docSettings)
		else:
			strErrorMessage = dctStatusResult.op_message

	if strNewStatus:
		_update_dn_status(dctDN["name"], strNewStatus, strOldStatus, strReferenceId)
	elif strErrorMessage:
		_log_skip_error(strReferenceId, strErrorMessage)


def _is_valid_reference_id(strReferenceId):
	return bool(strReferenceId)


def _resolve_order_status(strReferenceId, strBaseURL, dctHeaders, docSettings):
	dctOrderResult = _fetch_order(strReferenceId, strBaseURL, dctHeaders, docSettings)
	strResolvedStatus = ""

	if dctOrderResult.op_result:
		strResolvedStatus = "Pending"
	elif dctOrderResult.status_code == 404:
		strResolvedStatus = "Not Found"
	elif dctOrderResult.status_code == 401:
		dctTokenResult = get_token(blnForce=True)
		if dctTokenResult.op_result:
			dctHeaders = _build_headers(docSettings, dctTokenResult.token)
			dctOrderResult = _fetch_order(strReferenceId, strBaseURL, dctHeaders, docSettings)
			if dctOrderResult.op_result:
				strResolvedStatus = "Pending"
			elif dctOrderResult.status_code == 404:
				strResolvedStatus = "Not Found"
			else:
				_log_skip_error(strReferenceId, "GetOrder failed after refresh: " + dctOrderResult.op_message)
		else:
			_log_skip_error(strReferenceId, "Token refresh failed: " + dctTokenResult.op_message)
	else:
		_log_skip_error(strReferenceId, "GetOrder failed: " + dctOrderResult.op_message)

	return strResolvedStatus


def _fetch_shipment_status(strReferenceId, strBaseURL, dctHeaders, docSettings):
	strURL = strBaseURL + "/mngapi/api/standardqueryapi/getshipmentstatus/" + quote(strReferenceId, safe="")
	dctResponse = _dhl_get_with_retry(strURL, dctHeaders, docSettings, "DHL Get Shipment Status Response")

	if dctResponse.status_code == 200:
		dctData = dctResponse.body
		if isinstance(dctData, list) and len(dctData) > 0:
			dctData = dctData[0]
		dStatusCode = dctData.get("shipmentStatusCode") if isinstance(dctData, dict) else None
		strStatus = DHL_STATUS_MAP.get(dStatusCode)
		if strStatus:
			return frappe._dict({"op_result": True, "op_message": "", "status_code": 200, "status": strStatus})
		return frappe._dict({"op_result": False, "op_message": "Unknown shipmentStatusCode: {0}".format(dStatusCode), "status_code": 200, "status": ""})

	return frappe._dict({"op_result": False, "op_message": dctResponse.op_message, "status_code": dctResponse.status_code, "status": ""})


def _fetch_order(strReferenceId, strBaseURL, dctHeaders, docSettings):
	strURL = strBaseURL + "/mngapi/api/standardqueryapi/getorder/" + quote(strReferenceId, safe="")
	dctResponse = _dhl_get_with_retry(strURL, dctHeaders, docSettings, "DHL Get Order Response")

	if dctResponse.status_code == 200:
		return frappe._dict({"op_result": True, "op_message": "Order exists", "status_code": 200})

	return frappe._dict({"op_result": False, "op_message": dctResponse.op_message, "status_code": dctResponse.status_code})


def _dhl_get_with_retry(strURL, dctHeaders, docSettings, strLogTitle):
	dctResult = frappe._dict({"op_result": False, "op_message": "", "status_code": 0, "body": None})

	for dAttempt in range(MAX_RETRY_ATTEMPTS):
		try:
			_log_api_request(docSettings, strLogTitle + " Request", "GET", strURL, dctHeaders)
			objResponse = requests.get(strURL, headers=dctHeaders, timeout=30)
			dctResult.status_code = objResponse.status_code

			if objResponse.status_code == 200:
				dctResult.op_result = True
				dctResult.body = objResponse.json()
				break

			if objResponse.status_code == 404:
				dctResult.op_message = "Not found"
				break

			if objResponse.status_code == 401:
				dctResult.op_message = "Unauthorized"
				break

			dctResult.op_message = "HTTP {0}: {1}".format(objResponse.status_code, objResponse.text[:500])
			_log_api_response(docSettings, strLogTitle, objResponse)

			if dAttempt < MAX_RETRY_ATTEMPTS - 1 and 500 <= objResponse.status_code < 600:
				time.sleep(BACKOFF_SECONDS[dAttempt])
			else:
				break

		except Exception as e:
			dctResult.status_code = 0
			dctResult.op_message = "Exception: " + str(e)
			if dAttempt < MAX_RETRY_ATTEMPTS - 1:
				time.sleep(BACKOFF_SECONDS[dAttempt])
			else:
				break

	if not dctResult.op_result and dctResult.status_code not in (401, 404):
		frappe.log_error(strLogTitle + " Error", "URL: {0} | {1}".format(strURL, dctResult.op_message))

	return dctResult


def _update_dn_status(strDNName, strNewStatus, strOldStatus, strReferenceId):
	frappe.db.set_value(
		"Delivery Note",
		strDNName,
		{
			"dhl_shipment_status": strNewStatus,
			"dhl_last_tracked": now_datetime()
		},
		update_modified=False
	)

	if strNewStatus != strOldStatus:
		frappe.get_doc({
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": "Delivery Note",
			"reference_name": strDNName,
			"content": "DHL status updated: {0} (ref: {1})".format(strNewStatus, strReferenceId),
			"comment_email": frappe.session.user or "Administrator"
		}).insert(ignore_permissions=True)


def _log_skip_error(strReferenceId, strMessage):
	frappe.log_error(
		"DHL Hourly Tracking Skipped",
		"ReferenceId: {0} | {1}".format(strReferenceId, strMessage)
	)


def _log_api_response(docSettings, strTitle, objResponse):
	if docSettings.enable_detailed_logs:
		try:
			frappe.log_error(strTitle, frappe.as_json({
				"status_code": objResponse.status_code,
				"headers": dict(objResponse.headers),
				"body": objResponse.text
			}))
		except Exception:
			pass
